import uuid

from fastapi import APIRouter, Depends, status

from app.core.dependencies import DB, CurrentUser, Org
from app.core.rate_limit import rate_limit
from app.pathways import service
from app.pathways.models import ProcessorCapability
from app.pathways.schemas import CapabilityIn, CapabilityOut, PathwayReport, ProcessingMethodOut

router = APIRouter(tags=["processing pathways"])


def _cap_out(cap: ProcessorCapability) -> CapabilityOut:
    return CapabilityOut(id=cap.id, method_key=cap.method.key, method_name=cap.method.name, facility_id=cap.facility_id,
                         capacity_per_month=cap.capacity_per_month,
                         available_capacity_per_month=cap.available_capacity_per_month,
                         processing_cost_per_tonne=cap.processing_cost_per_tonne, cost_is_demo=cap.cost_is_demo,
                         max_input_distance_km=cap.max_input_distance_km)


@router.get("/resources/{resource_id}/processing-pathways", response_model=PathwayReport,
            dependencies=[Depends(rate_limit("search", 30, 60))],
            summary="Compare selling as-is with Seller → Processor → Buyer pathways")
def processing_pathways(resource_id: uuid.UUID, ctx: Org, db: DB) -> PathwayReport:
    return service.build_report(db, ctx, resource_id)


@router.get("/processing-methods", response_model=list[ProcessingMethodOut])
def processing_methods(_user: CurrentUser, db: DB) -> list[ProcessingMethodOut]:
    return [ProcessingMethodOut.model_validate(m) for m in service.list_methods(db)]


@router.get("/organizations/me/processor-capabilities", response_model=list[CapabilityOut])
def my_capabilities(ctx: Org, db: DB) -> list[CapabilityOut]:
    return [_cap_out(c) for c in service.list_capabilities(db, ctx)]


@router.post("/organizations/me/processor-capabilities", response_model=CapabilityOut,
             status_code=status.HTTP_201_CREATED, summary="Declare that your organization can run a processing method")
def add_capability(body: CapabilityIn, ctx: Org, db: DB) -> CapabilityOut:
    return _cap_out(service.add_capability(db, ctx, body))
