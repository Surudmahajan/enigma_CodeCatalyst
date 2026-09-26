import uuid

from fastapi import APIRouter, Query

from app.core.dependencies import DB, CurrentUser
from app.materials import service
from app.materials.schemas import (
    ApplicationTypeOut,
    CategoryOut,
    MaterialApplicationOut,
    MaterialOut,
    MaterialSummary,
    PropertyDefinitionOut,
)

router = APIRouter(tags=["materials"])


@router.get("/materials", response_model=list[MaterialSummary], summary="Search the normalized material catalogue")
def list_materials(_user: CurrentUser, db: DB, q: str | None = Query(default=None, max_length=100),
                   category: str | None = None) -> list[MaterialSummary]:
    return [MaterialSummary.model_validate(m) for m in service.list_materials(db, q, category)]


@router.get("/materials/categories", response_model=list[CategoryOut])
def list_categories(_user: CurrentUser, db: DB) -> list[CategoryOut]:
    return [CategoryOut(**c) for c in service.list_categories(db)]


@router.get("/materials/{material_id}", response_model=MaterialOut)
def get_material(material_id: uuid.UUID, _user: CurrentUser, db: DB) -> MaterialOut:
    return MaterialOut.model_validate(service.get_material(db, material_id))


@router.get("/materials/{material_id}/applications", response_model=list[MaterialApplicationOut],
            summary="Curated potential applications of a material")
def material_applications(material_id: uuid.UUID, _user: CurrentUser, db: DB) -> list[MaterialApplicationOut]:
    service.get_material(db, material_id)
    return [MaterialApplicationOut.model_validate(a) for a in service.list_material_applications(db, material_id)]


@router.get("/properties", response_model=list[PropertyDefinitionOut], summary="Technical property definitions")
def list_properties(_user: CurrentUser, db: DB) -> list[PropertyDefinitionOut]:
    return [PropertyDefinitionOut.model_validate(p) for p in service.list_property_definitions(db)]


@router.get("/applications", response_model=list[ApplicationTypeOut], summary="Industrial application types")
def list_applications(_user: CurrentUser, db: DB) -> list[ApplicationTypeOut]:
    return [ApplicationTypeOut.model_validate(a) for a in service.list_application_types(db)]
