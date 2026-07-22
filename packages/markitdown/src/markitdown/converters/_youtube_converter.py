import json
import os
import shutil
import subprocess
import time
import re
import tempfile
import bs4
from typing import Any, BinaryIO, Dict, List, Union
from urllib.parse import parse_qs, urlparse, unquote

from .._base_converter import DocumentConverter, DocumentConverterResult
from .._stream_info import StreamInfo
from ._transcribe_audio import transcribe_audio

# Optional YouTube transcription support
try:
    # Suppress some warnings on library import
    import warnings

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=SyntaxWarning)
        # Patch submitted upstream to fix the SyntaxWarning
        from youtube_transcript_api import YouTubeTranscriptApi

    IS_YOUTUBE_TRANSCRIPT_CAPABLE = True
except ModuleNotFoundError:
    IS_YOUTUBE_TRANSCRIPT_CAPABLE = False

# Optional Chinese text conversion support
try:
    import zhconv
    IS_ZHCONV_CAPABLE = True
except ModuleNotFoundError:
    IS_ZHCONV_CAPABLE = False


ACCEPTED_MIME_TYPE_PREFIXES = [
    "text/html",
    "application/xhtml",
]

ACCEPTED_FILE_EXTENSIONS = [
    ".html",
    ".htm",
]


class YouTubeConverter(DocumentConverter):
    """Handle YouTube specially, focusing on the video title, description, and transcript."""

    def _download_audio(self, url: str, audio_format: str = "mp3") -> str:
        """Download YouTube audio with yt-dlp and return a local file path."""
        if shutil.which("yt-dlp") is None:
            raise RuntimeError("yt-dlp is required for YouTube audio transcription")

        tmp_dir = tempfile.mkdtemp(prefix="markitdown_youtube_")
        output_template = os.path.join(tmp_dir, "audio.%(ext)s")
        try:
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
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

        audio_path = os.path.join(tmp_dir, f"audio.{audio_format}")
        if os.path.exists(audio_path):
            return audio_path

        for name in os.listdir(tmp_dir):
            if name.startswith("audio."):
                return os.path.join(tmp_dir, name)

        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError("yt-dlp completed but no audio file was produced")

    def _transcribe_audio_from_url(
        self,
        url: str,
        *,
        language: Union[str, None],
        sensevoice_workers: int,
    ) -> str:
        audio_path = self._download_audio(url, "mp3")
        tmp_dir = os.path.dirname(audio_path)
        try:
            with open(audio_path, "rb") as audio_stream:
                return transcribe_audio(
                    audio_stream,
                    audio_format="mp3",
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
        language: Union[str, None],
        prompt: Union[str, None] = None,
    ) -> str:
        """Ask an LLM to clean up ASR mistakes in the generated Markdown."""
        if prompt is None or prompt.strip() == "":
            prompt = (
                "You are an ASR transcript correction editor. Correct the Markdown transcript generated "
                "from a YouTube video without summarizing or omitting content. Preserve the top-level "
                "Markdown structure, title, Source URL, metadata, description, headings, and meaning. "
                "Rewrite only the transcript text where needed. Remove non-speech ASR event markers, "
                "fix obvious ASR mistakes, punctuation, sentence boundaries, names, technical terms, "
                "and broken phrases. Do not invent facts, examples, timestamps, numbers, or claims. "
                "Return only the complete corrected Markdown. "
                f"Transcript language hint: {language or 'auto'}."
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

    def accepts(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,  # Options to pass to the converter
    ) -> bool:
        """
        Make sure we're dealing with HTML content *from* YouTube.
        """
        url = stream_info.url or ""
        mimetype = (stream_info.mimetype or "").lower()
        extension = (stream_info.extension or "").lower()

        url = unquote(url)
        url = url.replace(r"\?", "?").replace(r"\=", "=")

        if not url.startswith("https://www.youtube.com/watch?"):
            # Not a YouTube URL
            return False

        if extension in ACCEPTED_FILE_EXTENSIONS:
            return True

        for prefix in ACCEPTED_MIME_TYPE_PREFIXES:
            if mimetype.startswith(prefix):
                return True

        # Not HTML content
        return False

    def convert(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,  # Options to pass to the converter
    ) -> DocumentConverterResult:
        # Parse the stream
        encoding = "utf-8" if stream_info.charset is None else stream_info.charset
        soup = bs4.BeautifulSoup(file_stream, "html.parser", from_encoding=encoding)

        # Read the meta tags
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
                    if key and content:  # Only add non-empty content
                        metadata[key] = content
                    break

        # Try reading the description
        try:
            for script in soup(["script"]):
                if not isinstance(script, bs4.Tag):
                    continue
                if not script.string:  # Skip empty scripts
                    continue
                content = script.string
                if "ytInitialData" in content:
                    match = re.search(r"var ytInitialData = ({.*?});", content)
                    if match:
                        data = json.loads(match.group(1))
                        attrdesc = self._findKey(data, "attributedDescriptionBodyText")
                        if attrdesc and isinstance(attrdesc, dict):
                            metadata["description"] = str(attrdesc.get("content", ""))
                    break
        except Exception as e:
            print(f"Error extracting description: {e}")
            pass

        # Start preparing the page
        page_url = str(stream_info.url or "")
        webpage_text = f"# YouTube\n\n- **Source URL:** {page_url}\n"

        title = self._get(metadata, ["title", "og:title", "name"])  # type: ignore
        assert isinstance(title, str)

        if title:
            webpage_text += f"\n## {title}\n"

        stats = ""
        views = self._get(metadata, ["interactionCount"])  # type: ignore
        if views:
            stats += f"- **Views:** {views}\n"

        keywords = self._get(metadata, ["keywords"])  # type: ignore
        if keywords:
            stats += f"- **Keywords:** {keywords}\n"

        runtime = self._get(metadata, ["duration"])  # type: ignore
        if runtime:
            stats += f"- **Runtime:** {runtime}\n"

        if len(stats) > 0:
            webpage_text += f"\n### Video Metadata\n{stats}\n"

        description = self._get(metadata, ["description", "og:description"])  # type: ignore
        if description:
            webpage_text += f"\n### Description\n{description}\n"

        transcript_text = ""
        transcribed_from_audio = False
        parsed_url = urlparse(page_url)
        params = parse_qs(parsed_url.query)

        if IS_YOUTUBE_TRANSCRIPT_CAPABLE and "v" in params and params["v"][0]:
            ytt_api = YouTubeTranscriptApi()  # type: ignore[name-defined]
            video_id = str(params["v"][0])
            languages = ["en"]
            transcript_list = None
            youtube_transcript_languages = languages
            try:
                transcript_list = ytt_api.list(video_id)
                for transcript in transcript_list:
                    languages.append(transcript.language_code)
                    break

                youtube_transcript_languages = kwargs.get(
                    "youtube_transcript_languages", languages
                )
                transcript = self._retry_operation(
                    lambda: ytt_api.fetch(
                        video_id, languages=youtube_transcript_languages
                    ),
                    retries=3,
                    delay=2,
                )

                if transcript:
                    transcript_text = " ".join([part.text for part in transcript])  # type: ignore
            except Exception as e:
                if len(languages) == 1:
                    print(f"Error fetching transcript: {e}")
                elif transcript_list is not None:
                    try:
                        transcript = (
                            transcript_list.find_transcript(languages)
                            .translate(youtube_transcript_languages[0])
                            .fetch()
                        )
                        transcript_text = " ".join([part.text for part in transcript])
                    except Exception as translate_exc:
                        print(f"Error fetching translated transcript: {translate_exc}")

        if not transcript_text and kwargs.get("youtube_transcribe_audio", True):
            try:
                transcript_text = self._transcribe_audio_from_url(
                    page_url,
                    language=kwargs.get("language"),
                    sensevoice_workers=kwargs.get("sensevoice_workers", 8),
                )
                transcribed_from_audio = bool(transcript_text)
            except Exception as exc:
                webpage_text += f"\n> Audio transcription failed: {exc}\n"

        if transcript_text:
            webpage_text += "\n### Transcript\n"
            if transcribed_from_audio:
                webpage_text += "\n> Generated from audio with ASR.\n\n"
            webpage_text += transcript_text + "\n"

        llm_client = kwargs.get("llm_client")
        llm_model = kwargs.get("llm_model")
        auto_correct = llm_client is not None and llm_model is not None
        if transcribed_from_audio and auto_correct and kwargs.get("youtube_correct_transcript", True):
            try:
                webpage_text = self._correct_markdown_with_llm(
                    webpage_text,
                    client=llm_client,
                    model=str(llm_model),
                    language=kwargs.get("language"),
                    prompt=kwargs.get("youtube_correction_prompt"),
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

        title = title if title else (soup.title.string if soup.title else "")
        assert isinstance(title, str)

        return DocumentConverterResult(
            markdown=webpage_text,
            title=title,
        )

    def _get(
        self,
        metadata: Dict[str, str],
        keys: List[str],
        default: Union[str, None] = None,
    ) -> Union[str, None]:
        """Get first non-empty value from metadata matching given keys."""
        for k in keys:
            if k in metadata:
                return metadata[k]
        return default

    def _findKey(self, json: Any, key: str) -> Union[str, None]:  # TODO: Fix json type
        """Recursively search for a key in nested dictionary/list structures."""
        if isinstance(json, list):
            for elm in json:
                ret = self._findKey(elm, key)
                if ret is not None:
                    return ret
        elif isinstance(json, dict):
            for k, v in json.items():
                if k == key:
                    return json[k]
                if result := self._findKey(v, key):
                    return result
        return None

    def _retry_operation(self, operation, retries=3, delay=2):
        """Retries the operation if it fails."""
        attempt = 0
        while attempt < retries:
            try:
                return operation()  # Attempt the operation
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                if attempt < retries - 1:
                    time.sleep(delay)  # Wait before retrying
                attempt += 1
        # If all attempts fail, raise the last exception
        raise Exception(f"Operation failed after {retries} attempts.")
