"""Standalone image converter with OCR support."""

from typing import Any, BinaryIO, Optional

from markitdown import DocumentConverter, DocumentConverterResult, StreamInfo

from ._ocr_service import LLMVisionOCRService


ACCEPTED_MIME_TYPE_PREFIXES = [
    "image/jpeg",
    "image/png",
]

ACCEPTED_FILE_EXTENSIONS = [".jpg", ".jpeg", ".png"]


class ImageConverterWithOCR(DocumentConverter):
    """Converts standalone images to markdown via the OCR LLM config."""

    def __init__(self, ocr_service: Optional[LLMVisionOCRService] = None):
        super().__init__()
        self.ocr_service = ocr_service

    def accepts(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,
    ) -> bool:
        if self.ocr_service is None and kwargs.get("ocr_service") is None:
            return False

        mimetype = (stream_info.mimetype or "").lower()
        extension = (stream_info.extension or "").lower()

        if extension in ACCEPTED_FILE_EXTENSIONS:
            return True

        return any(mimetype.startswith(prefix) for prefix in ACCEPTED_MIME_TYPE_PREFIXES)

    def convert(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,
    ) -> DocumentConverterResult:
        ocr_service: LLMVisionOCRService | None = (
            kwargs.get("ocr_service") or self.ocr_service
        )
        if ocr_service is None:
            return DocumentConverterResult(markdown="")

        ocr_result = ocr_service.extract_text(file_stream, stream_info=stream_info)
        if ocr_result.text.strip():
            return DocumentConverterResult(
                markdown=f"*[Image OCR]\n{ocr_result.text.strip()}\n[End OCR]*"
            )

        if ocr_result.error:
            return DocumentConverterResult(markdown=f"*[OCR error: {ocr_result.error}]*")

        return DocumentConverterResult(markdown="*[No text could be extracted from this image]*")
