import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.core.logging import request_id_ctx


def record(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Add an audit entry to the current transaction (committed with the change it describes)."""
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            organization_id=organization_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=_jsonable(details or {}),
            request_id=request_id_ctx.get(),
        )
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
