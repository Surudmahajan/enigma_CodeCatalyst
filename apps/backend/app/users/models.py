from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, Timestamps, UUIDPrimaryKey


class User(UUIDPrimaryKey, Timestamps, Base):
    """A human account. Business identity lives on Organization, not here."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)  # stored lower-cased
    phone: Mapped[str | None] = mapped_column(String(32))
    password_hash: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # Platform operators (admin console). Never granted through the public API.
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    memberships = relationship("OrganizationMember", back_populates="user", lazy="selectin")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()
