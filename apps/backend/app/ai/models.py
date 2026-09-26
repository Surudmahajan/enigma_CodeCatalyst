import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, JSONType, UUIDPrimaryKey
from app.core.time import utcnow


class AIOutputLog(UUIDPrimaryKey, Base):
    """Audit trail for every model call: which model and prompt version produced
    what, and whether validation accepted it. Inputs are stored as a hash only."""

    __tablename__ = "ai_output_logs"

    feature: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(32))
    input_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))  # ACCEPTED | REJECTED_VALIDATION | REFUSED | ERROR
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
