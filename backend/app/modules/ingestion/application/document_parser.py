from io import BytesIO
from pathlib import Path

from markitdown import MarkItDown


class UnsupportedDocumentError(ValueError):
    pass


class DocumentParser:
    """Convert supported office documents to normalized Markdown using MarkItDown."""

    supported_extensions = frozenset({".pdf", ".docx", ".txt", ".md", ".markdown"})

    def __init__(self) -> None:
        self.converter = MarkItDown(enable_plugins=False)

    def parse(self, content: bytes, *, filename: str) -> str:
        extension = Path(filename).suffix.lower()
        if extension not in self.supported_extensions:
            raise UnsupportedDocumentError(
                f"지원하지 않는 문서 형식입니다: {extension or '확장자 없음'}"
            )
        if extension in {".txt", ".md", ".markdown"}:
            text = content.decode("utf-8-sig").strip()
        else:
            result = self.converter.convert_stream(
                BytesIO(content),
                file_extension=extension,
            )
            text = (result.markdown or "").strip()
        if not text:
            raise ValueError("문서에서 텍스트를 추출하지 못했습니다.")
        return text
