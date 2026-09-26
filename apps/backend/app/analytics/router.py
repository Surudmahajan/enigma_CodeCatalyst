import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select

from app.analytics import service
from app.core.dependencies import DB, Org
from app.impact.models import ImpactRecord, ImpactSource, MetricType

router = APIRouter(tags=["dashboard & impact"])


class ImpactRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exchange_id: uuid.UUID
    match_id: uuid.UUID
    metric_type: MetricType
    value: Decimal
    unit: str
    calculation_method: str
    methodology_version: str
    source_type: ImpactSource
    uses_demo_factors: bool
    assumptions: list[str]
    inputs: dict[str, Any]
    verified_at: datetime | None
    created_at: datetime


@router.get("/dashboard", summary="Provider and demander dashboard counters for your organization")
def dashboard(ctx: Org, db: DB) -> dict[str, Any]:
    return service.org_dashboard(db, ctx)


@router.get("/impact/dashboard", summary="Potential vs realized impact, with methodology")
def impact_dashboard(ctx: Org, db: DB) -> dict[str, Any]:
    return service.impact_dashboard(db, ctx)


@router.get("/impact/records", response_model=list[ImpactRecordOut])
def impact_records(ctx: Org, db: DB, exchange_id: uuid.UUID | None = None) -> list[ImpactRecordOut]:
    query = select(ImpactRecord).where(or_(ImpactRecord.provider_org_id == ctx.org_id,
                                           ImpactRecord.demander_org_id == ctx.org_id))
    if exchange_id:
        query = query.where(ImpactRecord.exchange_id == exchange_id)
    return [ImpactRecordOut.model_validate(r) for r in db.scalars(query.order_by(ImpactRecord.created_at.desc()))]
