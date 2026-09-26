"""Private-by-default documents attached to an organization, conversation or listing."""

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.core.config import get_settings
from app.core.dependencies import OrgContext
from app.core.errors import AppError, ConflictError, NotFoundError, ValidationFailedError
from app.documents.models import Document, ScanStatus
from app.documents.storage import get_storage
from app.documents.validation import detect_type, safe_display_name, scan
from app.matching.lifecycle import CONNECTED_STATES
from app.matching.models import Match
from app.messaging import service as messaging
from app.messaging.models import Conversation, ConversationStatus
from app.organizations.permissions import Permission
from app.requirements.models import Requirement
from app.resources.models import Resource


class PayloadTooLarge(AppError):
    status_code = 413
    code = "FILE_TOO_LARGE"


def upload(db: Session, ctx: OrgContext, *, data: bytes, claimed_name: str,
           conversation_id: uuid.UUID | None = None, resource_id: uuid.UUID | None = None,
           requirement_id: uuid.UUID | None = None) -> Document:
    settings = get_settings()
    if len([t for t in (conversation_id, resource_id, requirement_id) if t]) > 1:
        raise ValidationFailedError("Attach a document to at most one conversation or listing.")
    if not data:
        raise ValidationFailedError("The file is empty.", code="FILE_EMPTY")
    if len(data) > settings.max_upload_bytes:
        raise PayloadTooLarge(f"Files must be {settings.max_upload_mb} MB or smaller.")

    conversation = None
    if conversation_id:
        ctx.require(Permission.SEND_MESSAGES)
        conversation = messaging.get_for_org(db, ctx, conversation_id)
        if conversation.status != ConversationStatus.ACTIVE:
            raise ConflictError("This conversation is closed.", code="CONVERSATION_CLOSED")
    else:
        ctx.require(Permission.MANAGE_LISTINGS)
    if resource_id:
        resource = db.get(Resource, resource_id)
        if resource is None or resource.organization_id != ctx.org_id:
            raise NotFoundError("The requested resource does not exist.", code="RESOURCE_NOT_FOUND")
    if requirement_id:
        requirement = db.get(Requirement, requirement_id)
        if requirement is None or requirement.organization_id != ctx.org_id:
            raise NotFoundError("The requested requirement does not exist.", code="REQUIREMENT_NOT_FOUND")

    detected = detect_type(data, claimed_name)
    scan_status = ScanStatus(scan(data))
    if scan_status == ScanStatus.INFECTED:
        audit.record(db, action="DOCUMENT_REJECTED_MALWARE", entity_type="document", entity_id=None,
                     actor_user_id=ctx.user.id, organization_id=ctx.org_id)
        db.commit()
        raise ValidationFailedError("The file was flagged by the malware scanner.", code="FILE_INFECTED")

    storage_key = f"documents/{ctx.org_id}/{uuid.uuid4().hex}{detected.extension}"
    get_storage().put(storage_key, data, detected.mime)
    document = Document(
        organization_id=ctx.org_id, uploaded_by_user_id=ctx.user.id, conversation_id=conversation_id,
        resource_id=resource_id, requirement_id=requirement_id, file_name=safe_display_name(claimed_name, detected),
        file_type=detected.mime, storage_key=storage_key, file_size=len(data),
        checksum_sha256=hashlib.sha256(data).hexdigest(), scan_status=scan_status,
    )
    db.add(document)
    db.flush()
    audit.record(db, action="DOCUMENT_UPLOADED", entity_type="document", entity_id=document.id,
                 actor_user_id=ctx.user.id, organization_id=ctx.org_id,
                 details={"file_type": detected.mime, "size": len(data),
                          "conversation_id": conversation_id, "resource_id": resource_id})
    db.commit()
    if conversation is not None:
        messaging.send_message(db, ctx, conversation.id, None, document_id=document.id)
    return document


def can_access(db: Session, ctx: OrgContext, document: Document) -> bool:
    if document.organization_id == ctx.org_id:
        return True
    if document.conversation_id:
        conversation = db.get(Conversation, document.conversation_id)
        return conversation is not None and ctx.org_id in messaging.participant_org_ids(conversation)
    # Listing documents are shared with organizations connected on a match for that listing.
    if document.resource_id:
        return db.scalars(select(Match.id).where(Match.resource_id == document.resource_id,
                                                 Match.demander_org_id == ctx.org_id,
                                                 Match.status.in_(CONNECTED_STATES))).first() is not None
    if document.requirement_id:
        return db.scalars(select(Match.id).where(Match.requirement_id == document.requirement_id,
                                                 Match.provider_org_id == ctx.org_id,
                                                 Match.status.in_(CONNECTED_STATES))).first() is not None
    return False


def get_accessible(db: Session, ctx: OrgContext, document_id: uuid.UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None or not can_access(db, ctx, document):
        raise NotFoundError("The requested document does not exist.", code="DOCUMENT_NOT_FOUND")
    return document


def read_content(document: Document) -> bytes:
    if document.scan_status == ScanStatus.INFECTED:
        raise NotFoundError("The requested document does not exist.", code="DOCUMENT_NOT_FOUND")
    return get_storage().get(document.storage_key)


def list_accessible(db: Session, ctx: OrgContext, *, conversation_id: uuid.UUID | None = None,
                    resource_id: uuid.UUID | None = None, requirement_id: uuid.UUID | None = None) -> list[Document]:
    query = select(Document)
    if conversation_id:
        messaging.get_for_org(db, ctx, conversation_id)
        query = query.where(Document.conversation_id == conversation_id)
    elif resource_id:
        query = query.where(Document.resource_id == resource_id)
    elif requirement_id:
        query = query.where(Document.requirement_id == requirement_id)
    else:
        query = query.where(Document.organization_id == ctx.org_id)
    return [d for d in db.scalars(query.order_by(Document.created_at.desc())) if can_access(db, ctx, d)]
