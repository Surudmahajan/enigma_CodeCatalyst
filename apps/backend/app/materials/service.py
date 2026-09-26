import uuid
from collections import defaultdict

from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationFailedError
from app.materials.models import ApplicationType, Material, MaterialApplication, PropertyDefinition


def list_materials(db: Session, q: str | None = None, category: str | None = None) -> list[Material]:
    query = select(Material).where(Material.is_active.is_(True))
    if category:
        query = query.where(Material.category == category)
    if q:
        like = f"%{q.strip().lower()}%"
        # Synonyms are JSON; a cast-to-text LIKE works on both SQLite and PostgreSQL.
        query = query.where(or_(func.lower(Material.canonical_name).like(like),
                                func.lower(cast(Material.synonyms, Text)).like(like),
                                func.lower(Material.category).like(like)))
    return list(db.scalars(query.order_by(Material.category, Material.canonical_name)))


def list_categories(db: Session) -> list[dict]:
    grouped: dict[str, set[str]] = defaultdict(set)
    counts: dict[str, int] = defaultdict(int)
    for m in db.scalars(select(Material).where(Material.is_active.is_(True))):
        counts[m.category] += 1
        if m.subcategory:
            grouped[m.category].add(m.subcategory)
    return [{"category": c, "subcategories": sorted(grouped[c]), "material_count": n} for c, n in sorted(counts.items())]


def get_material(db: Session, material_id: uuid.UUID) -> Material:
    material = db.get(Material, material_id)
    if material is None:
        raise NotFoundError("Material not found.", code="MATERIAL_NOT_FOUND")
    return material


def require_active_material(db: Session, material_id: uuid.UUID | None) -> Material | None:
    if material_id is None:
        return None
    material = db.get(Material, material_id)
    if material is None or not material.is_active:
        raise ValidationFailedError("Unknown material.", code="MATERIAL_NOT_FOUND",
                                    details={"material_id": str(material_id)})
    return material


def list_property_definitions(db: Session) -> list[PropertyDefinition]:
    return list(db.scalars(select(PropertyDefinition).order_by(PropertyDefinition.name)))


def properties_by_key(db: Session, keys: set[str]) -> dict[str, PropertyDefinition]:
    if not keys:
        return {}
    found = {p.key: p for p in db.scalars(select(PropertyDefinition).where(PropertyDefinition.key.in_(keys)))}
    missing = sorted(keys - found.keys())
    if missing:
        raise ValidationFailedError("Unknown property keys.", code="UNKNOWN_PROPERTY", details={"keys": missing})
    return found


def list_application_types(db: Session) -> list[ApplicationType]:
    return list(db.scalars(select(ApplicationType).order_by(ApplicationType.name)))


def require_application_type(db: Session, application_id: uuid.UUID | None) -> ApplicationType | None:
    if application_id is None:
        return None
    app_type = db.get(ApplicationType, application_id)
    if app_type is None:
        raise ValidationFailedError("Unknown application.", code="APPLICATION_NOT_FOUND")
    return app_type


def list_material_applications(db: Session, material_id: uuid.UUID | None = None,
                               application_type_id: uuid.UUID | None = None) -> list[MaterialApplication]:
    query = select(MaterialApplication)
    if material_id:
        query = query.where(MaterialApplication.material_id == material_id)
    if application_type_id:
        query = query.where(MaterialApplication.application_type_id == application_type_id)
    return list(db.scalars(query))
