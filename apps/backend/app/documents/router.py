import uuid
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from app.core.config import get_settings
from app.core.dependencies import DB, Org
from app.core.rate_limit import rate_limit
from app.documents import service
from app.documents.models import ScanStatus

router = APIRouter(prefix="/documents", tags=["documents"])


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    conversation_id: uuid.UUID | None
    resource_id: uuid.UUID | None
    requirement_id: uuid.UUID | None
    file_name: str
    file_type: str
    file_size: int
    checksum_sha256: str
    scan_status: ScanStatus
    created_at: datetime


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(rate_limit("uploads", 20, 60))],
             summary="Upload a specification sheet, test report, certificate or photo")
async def upload_document(
    ctx: Org, db: DB,
    file: UploadFile = File(...),
    conversation_id: uuid.UUID | None = Form(default=None),
    resource_id: uuid.UUID | None = Form(default=None),
    requirement_id: uuid.UUID | None = Form(default=None),
) -> DocumentOut:
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)  # read at most one byte past the limit
    document = service.upload(db, ctx, data=data, claimed_name=file.filename or "document",
                              conversation_id=conversation_id, resource_id=resource_id, requirement_id=requirement_id)
    return DocumentOut.model_validate(document)


@router.get("", response_model=list[DocumentOut])
def list_documents(ctx: Org, db: DB, conversation_id: uuid.UUID | None = None, resource_id: uuid.UUID | None = None,
                   requirement_id: uuid.UUID | None = None) -> list[DocumentOut]:
    return [DocumentOut.model_validate(d) for d in service.list_accessible(
        db, ctx, conversation_id=conversation_id, resource_id=resource_id, requirement_id=requirement_id)]


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: uuid.UUID, ctx: Org, db: DB) -> DocumentOut:
    return DocumentOut.model_validate(service.get_accessible(db, ctx, document_id))


@router.get("/{document_id}/download", response_class=Response, summary="Download (access-controlled)")
def download_document(document_id: uuid.UUID, ctx: Org, db: DB) -> Response:
    document = service.get_accessible(db, ctx, document_id)
    content = service.read_content(document)
    return Response(content=content, media_type=document.file_type, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(document.file_name)}",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    })
