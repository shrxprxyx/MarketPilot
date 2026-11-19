"""Text extraction for uploads (FR-RAG-01). Uploaded content is untrusted data
(SRS §10.4): control characters are stripped and nothing is executed."""
import hashlib
import io
import re

from docx import Document as DocxDocument
from pypdf import PdfReader

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = (".pdf", ".docx", ".txt", ".md")

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ExtractionError(Exception):
    """Safe-to-show reason the file could not be turned into text."""


def clean_text(text: str) -> str:
    text = _CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def content_hash(text: str) -> str:
    normalized = " ".join(text.split()).lower()
    return hashlib.sha256(normalized.encode()).hexdigest()


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if not name.endswith(ALLOWED_EXTENSIONS):
        raise ExtractionError("Unsupported file type. Use PDF, DOCX, TXT or Markdown.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ExtractionError("File is larger than 10 MB.")
    try:
        if name.endswith(".pdf"):
            if not data.startswith(b"%PDF"):
                raise ExtractionError("The file is not a valid PDF.")
            text = "\n\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
        elif name.endswith(".docx"):
            if not data.startswith(b"PK"):
                raise ExtractionError("The file is not a valid DOCX.")
            text = "\n\n".join(p.text for p in DocxDocument(io.BytesIO(data)).paragraphs)
        else:
            text = data.decode("utf-8")
    except ExtractionError:
        raise
    except UnicodeDecodeError as exc:
        raise ExtractionError("Text files must be UTF-8.") from exc
    except Exception as exc:  # corrupt/encrypted files raise assorted library errors
        raise ExtractionError("The file could not be read.") from exc
    text = clean_text(text)
    if not text:
        raise ExtractionError("No text could be extracted from the file.")
    return text
