"""Cheap content checks before an uploaded source reaches object storage."""

from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile


class UnsupportedUploadError(ValueError):
    pass


class InvalidUploadError(ValueError):
    pass


DOCUMENT_MIMES = {
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "application/octet-stream",
    },
    ".txt": {"text/plain", "application/octet-stream"},
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
    ".markdown": {"text/markdown", "text/plain", "application/octet-stream"},
}

AUDIO_MIMES = {
    "audio/webm": ".webm",
    "video/webm": ".webm",
    "audio/mp4": ".mp4",
    "video/mp4": ".mp4",
    "audio/x-m4a": ".mp4",
    "audio/m4a": ".mp4",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
}


def _mime(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def validate_document(filename: str | None, content_type: str | None, content: bytes) -> None:
    extension = Path(filename or "").suffix.lower()
    allowed = DOCUMENT_MIMES.get(extension)
    if allowed is None:
        raise UnsupportedUploadError("Supported document types: PDF, DOCX, TXT, MD")
    mime = _mime(content_type)
    if mime and mime not in allowed:
        raise UnsupportedUploadError("Document content type does not match its extension")

    if extension == ".pdf":
        valid = content.startswith(b"%PDF-")
    elif extension == ".docx":
        try:
            with ZipFile(BytesIO(content)) as archive:
                members = set(archive.namelist())
            valid = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= members
        except BadZipFile:
            valid = False
    else:
        try:
            text = content.decode("utf-8-sig")
            valid = "\x00" not in text
        except UnicodeDecodeError:
            valid = False
    if not valid:
        raise InvalidUploadError("Document content does not match its format")


def _audio_container(content: bytes) -> str | None:
    if content.startswith(b"\x1a\x45\xdf\xa3"):
        return ".webm"
    if len(content) >= 12 and content[4:8] == b"ftyp":
        return ".mp4"
    if content.startswith(b"RIFF") and content[8:12] == b"WAVE":
        return ".wav"
    if content.startswith(b"ID3") or (
        len(content) >= 2 and content[0] == 0xFF and content[1] & 0xE0 == 0xE0
    ):
        return ".mp3"
    if content.startswith(b"OggS"):
        return ".ogg"
    if content.startswith(b"fLaC"):
        return ".flac"
    return None


def validate_recording(filename: str | None, content_type: str | None, content: bytes) -> str:
    """Return the verified extension; browsers can send MP4 as recording.webm."""
    mime = _mime(content_type)
    expected = AUDIO_MIMES.get(mime)
    if expected is None:
        raise UnsupportedUploadError("Unsupported recording content type")
    actual = _audio_container(content)
    if actual != expected:
        raise InvalidUploadError("Recording content does not match its content type")
    extension = Path(filename or "").suffix.lower()
    if (
        extension
        and extension != actual
        and not (actual == ".mp4" and extension in {".webm", ".m4a"})
    ):
        raise InvalidUploadError("Recording filename does not match its format")
    return actual
