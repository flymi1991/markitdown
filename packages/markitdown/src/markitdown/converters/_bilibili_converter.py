import json
import os
import re
import shutil
import subprocess
import tempfile
import bs4
from typing import Any, BinaryIO, Dict, List, Union
from urllib.parse import urlparse, unquote

from .._base_converter import DocumentConverter, DocumentConverterResult
from .._stream_info import StreamInfo
from ._transcribe_audio import transcribe_audio

try:
    import zhconv
    IS_ZHCONV_CAPABLE = True
except ModuleNotFoundError:
    IS_ZHCONV_CAPABLE = False

try:
    import requests
    IS_REQUESTS_CAPABLE = True
except ModuleNotFoundError:
    IS_REQUESTS_CAPABLE = False

BILIBILI_DOMAINS = ["www.bilibili.com", "bilibili.com", "b23.tv"]
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

ACCEPTED_MIME_TYPE_PREFIXES = [
    "text/html",
    "application/xhtml",
]

ACCEPTED_FILE_EXTENSIONS = [
    ".html",
    ".htm",
]


class BilibiliConverter(DocumentConverter):
    """Handle Bilibili video pages, extracting title, description, and subtitles."""

    def accepts(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,
    ) -> bool:
        url = stream_info.url or ""
        mimetype = (stream_info.mimetype or "").lower()
        extension = (stream_info.extension or "").lower()

        url = unquote(url)
        parsed = urlparse(url)
        host = parsed.netloc.lower()

        # Must be a Bilibili domain
        if not any(domain in host for domain in BILIBILI_DOMAINS):
            return False

        # Must be a video page
        if not re.search(r'/video/BV', parsed.path):
            return False

        if extension in ACCEPTED_FILE_EXTENSIONS:
            return True

        for prefix in ACCEPTED_MIME_TYPE_PREFIXES:
            if mimetype.startswith(prefix):
                return True

        return False

    def _fetch_page(self, url: str) -> str:
        """Fetch Bilibili page with browser-like headers."""
        if not IS_REQUESTS_CAPABLE:
            return ""
        try:
            resp = requests.get(url, headers=BROWSER_HEADERS, timeout=15)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            pass
        return ""

    def _parse_html(self, html: str):
        """Parse Bilibili HTML and return (soup, metadata, init_state)."""
        soup = bs4.BeautifulSoup(html, "html.parser")
        metadata: Dict[str, str] = {}

        if soup.title and soup.title.string:
            metadata["title"] = soup.title.string

        for meta in soup(["meta"]):
            if not isinstance(meta, bs4.Tag):
                continue
            for a in meta.attrs:
                if a in ["itemprop", "property", "name"]:
                    key = str(meta.get(a, ""))
                    content = str(meta.get("content", ""))
                    if key and content:
                        metadata[key] = content
                    break

        init_state = None
        for script in soup(["script"]):
            if not isinstance(script, bs4.Tag) or not script.string:
                continue
            if "__INITIAL_STATE__" in script.string:
                match = re.search(r'__INITIAL_STATE__\s*=\s*({.*?});', script.string, re.DOTALL)
                if match:
                    try:
                        init_state = json.loads(match.group(1))
                        break
                    except json.JSONDecodeError:
                        pass

        return soup, metadata, init_state

    def _fetch_subtitle(self, sub_url: str) -> str:
        """Fetch subtitle JSON and return concatenated text."""
        try:
            if sub_url.startswith("//"):
                sub_url = "https:" + sub_url
            resp = requests.get(sub_url, headers=BROWSER_HEADERS, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    parts = [item.get("content", "") for item in data if isinstance(item, dict)]
                    return " ".join(parts)
        except Exception:
            pass
        return ""

    def _download_audio(self, url: str, audio_format: str = "wav") -> str:
        """Download Bilibili audio with yt-dlp and return a local file path."""
        if shutil.which("yt-dlp") is None:
            raise RuntimeError("yt-dlp is required for Bilibili audio transcription")

        tmp_dir = tempfile.mkdtemp(prefix="markitdown_bilibili_")
        output_template = os.path.join(tmp_dir, "audio.%(ext)s")
        subprocess.run(
            [
                "yt-dlp",
                "--no-playlist",
                "-x",
                "--audio-format",
                audio_format,
                "-o",
                output_template,
                url,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        audio_path = os.path.join(tmp_dir, f"audio.{audio_format}")
        if not os.path.exists(audio_path):
            for name in os.listdir(tmp_dir):
                if name.startswith("audio."):
                    return os.path.join(tmp_dir, name)
            raise RuntimeError("yt-dlp completed but no audio file was produced")
        return audio_path

    def _transcribe_audio_from_url(
        self,
        url: str,
        *,
        language: str,
        sensevoice_workers: int,
    ) -> str:
        audio_path = self._download_audio(url, "wav")
        tmp_dir = os.path.dirname(audio_path)
        try:
            with open(audio_path, "rb") as audio_stream:
                return transcribe_audio(
                    audio_stream,
                    audio_format="wav",
                    language=language,
                    sensevoice_workers=sensevoice_workers,
                )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _correct_markdown_with_llm(
        self,
        markdown: str,
        *,
        client: Any,
        model: str,
        language: str,
        prompt: Union[str, None] = None,
    ) -> str:
        """Ask an LLM to clean up ASR mistakes in the generated Markdown."""
        if prompt is None or prompt.strip() == "":
            prompt = (
                "You are an ASR transcript correction editor. Correct the Markdown transcript generated "
                "from a Bilibili video without summarizing or omitting content. Preserve the top-level "
                "Markdown structure, title, Source URL, metadata, description, headings, and meaning. "
                "Rewrite only the transcript text where needed. Remove non-speech ASR event markers such "
                "as music notes, emoji, repeated smile markers, and stage/noise markers (for example: 🎼, 😊). "
                "Fix obvious ASR mistakes, especially homophones, dropped words, broken phrases across "
                "paragraphs, punctuation, and sentence boundaries. Correct product names, model names, "
                "people names, company names, English technical terms, and Markdown/AI terminology. "
                "Actively recover missing domain-specific words when the surrounding context strongly "
                "implies them. ASR often drops short but important technical words, nouns, connectors, "
                "units, and software-operation terms; restore them when needed to make the sentence "
                "technically coherent. Infer the most likely missing domain terms from nearby context, "
                "especially when a sentence contains incomplete operation steps, broken noun phrases, "
                "missing objects, missing units, or incomplete software/tool names. "
                "Keep terms consistent, such as Markdown, Obsidian, OneNote, AI Agent, ChatGPT, Claude, "
                "Gemini, MiniMax, and API when they appear in context. Restore natural Chinese wording, "
                "for example correcting likely ASR errors such as 能力数/能力术 to 能力树 when the context "
                "is knowledge or capability structure. Merge accidentally split phrases across paragraph "
                "boundaries, and split overly long transcript blocks into coherent semantic paragraphs. "
                "Do not invent new examples, facts, numbers, timestamps, or claims that are not supported "
                "by the transcript. However, do not be overly conservative: if an omitted or garbled term "
                "is necessary for the sentence and is strongly supported by nearby words, restore it. "
                "Do not replace uncertain content with a summary. If a word is uncertain, choose the most "
                "contextually likely correction while preserving the original meaning. Return only the "
                "complete corrected Markdown. "
                f"Transcript language hint: {language}."
            )

        messages = [
            {
                "role": "user",
                "content": f"{prompt}\n\n--- Markdown to correct ---\n{markdown}",
            }
        ]
        response = client.chat.completions.create(model=model, messages=messages)
        content = response.choices[0].message.content
        return content.strip() if content else markdown

    def convert(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,
    ) -> DocumentConverterResult:
        url = stream_info.url or ""

        # Read the stream content
        stream_html = file_stream.read().decode("utf-8", errors="replace")

        # Check if the stream content has video data (not a 412 error page)
        has_video_data = "__INITIAL_STATE__" in stream_html
        if not has_video_data and IS_REQUESTS_CAPABLE:
            stream_html = self._fetch_page(url)

        soup, metadata, init_state = self._parse_html(stream_html)

        # Extract video ID from URL
        video_id = None
        bv_match = re.search(r'BV[a-zA-Z0-9]+', url)
        if bv_match:
            video_id = bv_match.group(0)

        webpage_text = f"# Bilibili\n\n- **Source URL:** {url}\n"

        # Title
        title = ""
        if init_state:
            vd = init_state.get("videoData", {}) or {}
            title = vd.get("title", "") or metadata.get("title", "")
        else:
            title = metadata.get("title", "") or metadata.get("og:title", "")

        if title:
            webpage_text += f"\n## {title}\n"

        # Description
        description = ""
        if init_state:
            vd = init_state.get("videoData", {}) or {}
            description = vd.get("desc", "") or ""
        if not description:
            description = metadata.get("description", "") or metadata.get("og:description", "")

        # Video metadata
        stats = ""
        if init_state:
            vd = init_state.get("videoData", {}) or {}
            stat = vd.get("stat", {}) or {}
            if stat.get("view"):
                stats += f"- **Views:** {stat['view']}\n"
            if stat.get("like"):
                stats += f"- **Likes:** {stat['like']}\n"
            if stat.get("danmaku"):
                stats += f"- **Danmaku:** {stat['danmaku']}\n"
            owner = vd.get("owner", {}) or {}
            if owner.get("name"):
                stats += f"- **Uploader:** {owner['name']}\n"
            if vd.get("duration"):
                stats += f"- **Duration:** {vd['duration']}s\n"

        if stats:
            webpage_text += f"\n### Video Metadata\n{stats}\n"

        if description:
            webpage_text += f"\n### Description\n{description}\n"

        # Try to get subtitles from INITIAL_STATE
        transcript_text = ""
        if init_state:
            vd = init_state.get("videoData", {}) or {}
            for sub in (vd.get("subtitle", {}) or {}).get("list", []) or []:
                sub_url = sub.get("subtitle_url", "") or ""
                if sub_url:
                    transcript_text = self._fetch_subtitle(sub_url)
                    if transcript_text:
                        break

        # Fallback: try the view API
        if not transcript_text and video_id and IS_REQUESTS_CAPABLE:
            try:
                view_resp = requests.get(
                    f"https://api.bilibili.com/x/web-interface/view?bvid={video_id}",
                    headers=BROWSER_HEADERS, timeout=10
                )
                view_data = view_resp.json().get("data", {})
                if view_data:
                    for sub in (view_data.get("subtitle", {}) or {}).get("list", []) or []:
                        sub_url = sub.get("subtitle_url", "") or ""
                        if sub_url:
                            transcript_text = self._fetch_subtitle(sub_url)
                            if transcript_text:
                                break
            except Exception:
                pass

        transcribed_from_audio = False
        if not transcript_text and kwargs.get("bilibili_transcribe_audio"):
            try:
                transcript_text = self._transcribe_audio_from_url(
                    url,
                    language=kwargs.get("language", "zh"),
                    sensevoice_workers=kwargs.get("sensevoice_workers", 8),
                )
                transcribed_from_audio = bool(transcript_text)
            except Exception as exc:
                webpage_text += f"\n> Audio transcription failed: {exc}\n"

        if transcript_text:
            if transcribed_from_audio:
                webpage_text += "\n### Transcript\n"
                webpage_text += "\n> Generated from audio with SenseVoice.\n\n"
                webpage_text += transcript_text + "\n"
            else:
                webpage_text += f"\n### Transcript\n{transcript_text}\n"
        else:
            webpage_text += "\n> No subtitles available for this video.\n"

        llm_client = kwargs.get("llm_client")
        llm_model = kwargs.get("llm_model")
        auto_correct = llm_client is not None and llm_model is not None
        if auto_correct and kwargs.get("bilibili_correct_transcript", True):
            try:
                webpage_text = self._correct_markdown_with_llm(
                    webpage_text,
                    client=llm_client,
                    model=str(llm_model),
                    language=kwargs.get("language", "zh"),
                    prompt=kwargs.get("bilibili_correction_prompt"),
                )
            except Exception as exc:
                webpage_text += f"\n> LLM transcript correction failed: {exc}\n"

        if transcript_text and IS_ZHCONV_CAPABLE:
            webpage_text = zhconv.convert(webpage_text, "zh-hans")  # type: ignore[name-defined]
            title = zhconv.convert(title, "zh-hans")  # type: ignore[name-defined]

        # Convert to Simplified Chinese if requested
        if kwargs.get("convert_to_simplified_chinese") and IS_ZHCONV_CAPABLE:
            webpage_text = zhconv.convert(webpage_text, "zh-hans")  # type: ignore[name-defined]
            title = zhconv.convert(title, "zh-hans")  # type: ignore[name-defined]

        title = title or (soup.title.string if soup.title else "")
        return DocumentConverterResult(markdown=webpage_text, title=title)
