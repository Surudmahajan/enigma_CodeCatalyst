import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.ai import applications, classification, explanations, extraction, llm
from app.ai.embeddings import embedding_model_name
from app.core.config import get_settings
from app.core.dependencies import DB, CurrentUser, Org
from app.core.errors import ValidationFailedError
from app.core.rate_limit import rate_limit
from app.documents import service as documents
from app.materials.schemas import ClassificationRequest, ClassificationResponse, ClassificationSuggestion, MaterialSummary
from app.matching import service as matching
from app.organizations.permissions import Permission
from app.resources import service as resources

router = APIRouter(tags=["ai assistance"])
_ai_limit = Depends(rate_limit("ai", 20, 60))


class ExtractRequest(BaseModel):
    resource_id: uuid.UUID


class ExtractedOut(BaseModel):
    property_key: str
    value: Decimal
    snippet: str
    method: str
    confidence: float


class ExtractResponse(BaseModel):
    method: str
    text_chars: int
    suggestions: list[ExtractedOut]
    skipped: list[dict[str, Any]]
    notes: list[str]
    next_step: str = "Review each suggested value on the resource and confirm or reject it before it is used."


@router.get("/ai/status", summary="Which AI features are active")
def ai_status(_user: CurrentUser) -> dict[str, Any]:
    settings = get_settings()
    return {"llm_enabled": llm.is_enabled(), "provider": settings.ai_provider,
            "model": settings.ai_model if llm.is_enabled() else None, "embedding_model": embedding_model_name(),
            "note": "Matching and assessments are deterministic and work without an AI provider."}


@router.post("/materials/classify", response_model=ClassificationResponse, dependencies=[_ai_limit],
             summary="Suggest canonical materials for a free-text description")
def classify(body: ClassificationRequest, _user: CurrentUser, db: DB) -> ClassificationResponse:
    return ClassificationResponse(suggestions=[
        ClassificationSuggestion(material=MaterialSummary.model_validate(s["material"]), confidence=s["confidence"],
                                 reasons=s["reasons"], source=s["source"])
        for s in classification.classify(db, body.text)
    ])


@router.post("/documents/{document_id}/extract", response_model=ExtractResponse, dependencies=[_ai_limit],
             summary="Extract property suggestions from a specification document")
def extract(document_id: uuid.UUID, body: ExtractRequest, ctx: Org, db: DB) -> ExtractResponse:
    ctx.require(Permission.MANAGE_LISTINGS)
    document = documents.get_accessible(db, ctx, document_id)
    if document.organization_id != ctx.org_id:
        raise ValidationFailedError("You can only extract from your own organization's documents.",
                                    code="DOCUMENT_NOT_OWNED")
    resource = resources.get_owned(db, ctx, body.resource_id)
    result = extraction.extract_for_resource(db, resource, document.id, documents.read_content(document),
                                             document.file_type)
    return ExtractResponse(method=result.method, text_chars=result.text_chars, skipped=result.skipped,
                           notes=result.notes, suggestions=[ExtractedOut(**vars(s)) for s in result.suggestions])


@router.get("/resources/{resource_id}/application-suggestions", summary="Potential applications for a resource")
def application_suggestions(resource_id: uuid.UUID, ctx: Org, db: DB) -> dict[str, Any]:
    return applications.discover(db, resources.get_owned(db, ctx, resource_id))


@router.post("/matches/{match_id}/ai-summary", dependencies=[_ai_limit],
             summary="Optional AI rewording of the match explanation (fact-checked)")
def ai_summary(match_id: uuid.UUID, ctx: Org, db: DB) -> dict[str, Any]:
    return explanations.generate(db, matching.get_for_org(db, ctx, match_id))
