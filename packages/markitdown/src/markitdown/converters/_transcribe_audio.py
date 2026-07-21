import io
import importlib.util
import math
import os
import shutil
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import BinaryIO, Optional
from .._exceptions import MissingDependencyException

# Try loading optional dependencies
_dep_exc_info = None
_sr_available = False
_whisper_available = False
_sensevoice_available = False
_sensevoice_model = None
_sensevoice_model_lock = threading.Lock()

SENSEVOICE_CHUNK_THRESHOLD_BYTES = 20 * 1024 * 1024
SENSEVOICE_MAX_WORKERS = 8
SENSEVOICE_MODEL_NAME = "iic/SenseVoiceSmall"
SENSEVOICE_MODEL_DIRNAME = "SenseVoiceSmall"
SENSEVOICE_REQUIRED_FILES = [
    "model.pt",
    "config.yaml",
    "configuration.json",
    "tokens.json",
    "chn_jpn_yue_eng_ko_spectok.bpe.model",
    "am.mvn",
]

_sr_available = (
    importlib.util.find_spec("speech_recognition") is not None
    and importlib.util.find_spec("pydub") is not None
)
_whisper_available = importlib.util.find_spec("whisper") is not None
_sensevoice_available = importlib.util.find_spec("funasr") is not None


def _get_local_sensevoice_model_path() -> Optional[str]:
    override = os.environ.get("MARKITDOWN_SENSEVOICE_MODEL")
    if override and _is_sensevoice_model_dir(Path(override)):
        return override

    for candidate in _sensevoice_model_candidates():
        if _is_sensevoice_model_dir(candidate):
            return str(candidate)

    return None


def _sensevoice_model_candidates() -> list[Path]:
    package_dir = Path(__file__).resolve().parents[1]
    source_package_root = Path(__file__).resolve().parents[3]
    env_model_dir = _get_env_sensevoice_model_dir()
    return [
        env_model_dir,
        env_model_dir / SENSEVOICE_MODEL_DIRNAME,
        package_dir / "models" / SENSEVOICE_MODEL_DIRNAME,
        source_package_root / "models" / SENSEVOICE_MODEL_DIRNAME,
    ]


def _get_env_sensevoice_model_dir() -> Path:
    return Path(sys.prefix) / "share" / "markitdown" / "models"


def _is_sensevoice_model_dir(path: Path) -> bool:
    return all((path / name).is_file() for name in SENSEVOICE_REQUIRED_FILES)


def _find_cached_sensevoice_model_dir() -> Optional[Path]:
    cache_root = Path.home() / ".cache" / "modelscope" / "models" / "iic--SenseVoiceSmall" / "snapshots"
    if not cache_root.is_dir():
        return None
    for candidate in sorted(cache_root.iterdir(), reverse=True):
        if candidate.is_dir() and _is_sensevoice_model_dir(candidate):
            return candidate
    return None


def install_sensevoice_model(source_dir: Optional[str] = None) -> str:
    """Copy SenseVoiceSmall model files into the current Python environment."""
    if source_dir:
        source = Path(source_dir)
    else:
        current = _get_local_sensevoice_model_path()
        source = Path(current) if current else (_find_cached_sensevoice_model_dir() or Path())

    if not source or not _is_sensevoice_model_dir(source):
        raise FileNotFoundError(
            "SenseVoiceSmall model files were not found. Download them from "
            "https://www.modelscope.cn/models/iic/SenseVoiceSmall and pass the directory "
            "to --install-sensevoice-model."
        )

    target = _get_env_sensevoice_model_dir()
    target.mkdir(parents=True, exist_ok=True)
    for name in SENSEVOICE_REQUIRED_FILES:
        shutil.copy2(source / name, target / name)
    return str(target)


def _get_sensevoice_model(device: str = "cpu"):
    global _sensevoice_model
    if _sensevoice_model is None:
        with _sensevoice_model_lock:
            if _sensevoice_model is None:
                from funasr import AutoModel
                _sensevoice_model = AutoModel(
                    model=_get_local_sensevoice_model_path() or SENSEVOICE_MODEL_NAME,
                    device=device,
                    disable_update=True,
                )
    return _sensevoice_model


def transcribe_audio(
    file_stream: BinaryIO,
    *,
    audio_format: str = "wav",
    language: Optional[str] = None,
    whisper_model: str = "base",
    sensevoice_device: str = "cpu",
    sensevoice_workers: int = SENSEVOICE_MAX_WORKERS,
) -> str:
    # First try SenseVoice (best for Chinese)
    if _sensevoice_available:
        return _transcribe_with_sensevoice(
            file_stream, audio_format, language, sensevoice_device, sensevoice_workers
        )

    # Fallback to Whisper (local, no internet needed)
    if _whisper_available:
        return _transcribe_with_whisper(file_stream, audio_format, language, whisper_model)

    # Fallback to Google Speech Recognition
    if _sr_available:
        return _transcribe_with_google(file_stream, audio_format)

    raise MissingDependencyException(
        "Speech transcription requires installing funasr, openai-whisper, or markitdown[audio-transcription]. "
        "E.g., `pip install funasr` or `pip install openai-whisper`"
    )


def _transcribe_with_sensevoice(
    file_stream: BinaryIO,
    audio_format: str,
    language: Optional[str],
    device: str,
    max_workers: int,
) -> str:
    suffix = f".{audio_format}" if audio_format != "mp4" else ".m4a"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_stream.read())
        tmp_path = tmp.name

    try:
        if os.path.getsize(tmp_path) > SENSEVOICE_CHUNK_THRESHOLD_BYTES:
            text = _transcribe_sensevoice_chunks(
                tmp_path, audio_format, language, device, max_workers
            )
        else:
            text = _transcribe_sensevoice_file(tmp_path, language, device)
        return text if text else "[No speech detected]"
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _transcribe_sensevoice_file(
    audio_path: str,
    language: Optional[str],
    device: str,
) -> str:
    model = _get_sensevoice_model(device)
    sensevoice_lang = _map_language(language)
    res = model.generate(
        input=audio_path,
        language=sensevoice_lang,
        use_itn=True,
    )
    from funasr.utils.postprocess_utils import rich_transcription_postprocess
    return rich_transcription_postprocess(res[0]["text"]).strip()


def _transcribe_sensevoice_chunks(
    audio_path: str,
    audio_format: str,
    language: Optional[str],
    device: str,
    max_workers: int,
) -> str:
    chunk_paths = _split_audio_for_sensevoice(audio_path, audio_format)
    if not chunk_paths:
        return ""

    workers = max(1, min(max_workers, len(chunk_paths)))
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            texts = list(
                executor.map(
                    lambda path: _transcribe_sensevoice_file(path, language, device),
                    chunk_paths,
                )
            )
        return "\n".join(text for text in texts if text)
    finally:
        for path in chunk_paths:
            try:
                os.unlink(path)
            except Exception:
                pass


def _split_audio_for_sensevoice(audio_path: str, audio_format: str) -> list[str]:
    if not _sr_available:
        return [audio_path]

    import pydub

    source_format = "mp4" if audio_format == "mp4" else audio_format
    audio_segment = pydub.AudioSegment.from_file(audio_path, format=source_format)
    source_size = max(os.path.getsize(audio_path), 1)
    chunk_count = max(2, math.ceil(source_size / SENSEVOICE_CHUNK_THRESHOLD_BYTES))
    chunk_ms = math.ceil(len(audio_segment) / chunk_count)

    chunk_paths = []
    for start_ms in range(0, len(audio_segment), chunk_ms):
        chunk = audio_segment[start_ms : start_ms + chunk_ms]
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            chunk_path = tmp.name
        chunk.export(chunk_path, format="wav")
        chunk_paths.append(chunk_path)
    return chunk_paths


def _map_language(language: Optional[str]) -> str:
    if language is None:
        return "auto"
    lang = language.lower()[:2]
    if lang in ("zh", "ja", "en", "ko", "yue"):
        return lang
    return "auto"


def _transcribe_with_whisper(
    file_stream: BinaryIO,
    audio_format: str,
    language: Optional[str],
    model_size: str,
) -> str:
    # Save stream to a temp file (Whisper needs a file path)
    suffix = f".{audio_format}" if audio_format != "mp4" else ".m4a"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_stream.read())
        tmp_path = tmp.name

    try:
        import whisper

        model = whisper.load_model(model_size)
        opts = {"language": language} if language else {}
        result = model.transcribe(tmp_path, **opts)
        text = result.get("text", "").strip()
        return text if text else "[No speech detected]"
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _transcribe_with_google(
    file_stream: BinaryIO,
    audio_format: str,
) -> str:
    if audio_format in ["wav", "aiff", "flac"]:
        audio_source = file_stream
    elif audio_format in ["mp3", "mp4"]:
        import pydub

        audio_segment = pydub.AudioSegment.from_file(file_stream, format=audio_format)
        audio_source = io.BytesIO()
        audio_segment.export(audio_source, format="wav")
        audio_source.seek(0)
    else:
        raise ValueError(f"Unsupported audio format: {audio_format}")

    import speech_recognition as sr

    recognizer = sr.Recognizer()
    with sr.AudioFile(audio_source) as source:
        audio = recognizer.record(source)
        transcript = recognizer.recognize_google(audio).strip()
        return "[No speech detected]" if transcript == "" else transcript
