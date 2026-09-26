"""Upload validation: detect file type from content (magic bytes), never from the
client-supplied filename or MIME type, and produce a safe display name."""

import io
import re
import zipfile
from dataclasses import dataclass

from app.core.errors import ValidationFailedError

EICAR_SIGNATURE = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!"


@dataclass(frozen=True)
class DetectedType:
    mime: str
    extension: str


def _zip_office_type(data: bytes) -> DetectedType | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        return None
    if "[Content_Types].xml" not in names:
        return None
    if any(n.endswith("vbaProject.bin") for n in names):
        raise ValidationFailedError("Macro-enabled Office files are not allowed.", code="FILE_TYPE_NOT_ALLOWED")
    if "word/document.xml" in names:
        return DetectedType("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx")
    if "xl/workbook.xml" in names:
        return DetectedType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx")
    return None


def detect_type(data: bytes, claimed_name: str) -> DetectedType:
    if data.startswith(b"%PDF-"):
        return DetectedType("application/pdf", ".pdf")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return DetectedType("image/png", ".png")
    if data.startswith(b"\xff\xd8\xff"):
        return DetectedType("image/jpeg", ".jpg")
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return DetectedType("image/webp", ".webp")
    if data.startswith(b"PK\x03\x04"):
        office = _zip_office_type(data)
        if office:
            return office
    if b"\x00" not in data[:8192]:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            if claimed_name.lower().endswith(".csv"):
                return DetectedType("text/csv", ".csv")
            return DetectedType("text/plain", ".txt")
    raise ValidationFailedError(
        "Unsupported file type. Allowed: PDF, PNG, JPEG, WEBP, DOCX, XLSX, CSV, TXT.", code="FILE_TYPE_NOT_ALLOWED")


_UNSAFE = re.compile(r"[^A-Za-z0-9._ \-()]+")


def safe_display_name(claimed_name: str, detected: DetectedType) -> str:
    base = re.split(r"[\\/]", claimed_name or "")[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    stem = _UNSAFE.sub("_", stem).strip(" ._") or "document"
    return f"{stem[:120]}{detected.extension}"


def scan(data: bytes) -> str:
    """Malware scan hook. Built in: EICAR test-signature detection only.

    Production should call a real scanner (e.g. ClamAV via clamd) here; the
    result is stored on the Document so infected files are never served.
    """
    return "INFECTED" if EICAR_SIGNATURE in data else "NOT_SCANNED"
