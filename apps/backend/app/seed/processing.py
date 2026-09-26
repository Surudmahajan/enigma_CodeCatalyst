"""Processing knowledge: processed products and transformation methods (demo data).

The method specification (output properties, yield, time, indicative cost) is a
screening assumption curated for the demo, labelled as such in every pathway
result. It is not a vendor datasheet or a market price.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.materials.models import ApplicationType, Material, MaterialApplication, PhysicalState
from app.pathways.models import ProcessingMethod

DEMO_NOTE = ("Demo screening specification: typical outcome of weathering + crushing + screening of BOF slag, "
             "curated for the SYMBIO hackathon demo. Confirm with lab tests and the applicable standard.")

PROCESSED_MATERIALS = [
    ("Processed Slag Aggregate", "Processed aggregate", "Slag aggregate", PhysicalState.SOLID,
     "Weathered, crushed and screened steel slag graded for road and construction use.",
     ["processed slag aggregate", "graded slag aggregate", "steel slag aggregate", "weathered slag aggregate"],
     ["road_subbase", "concrete_aggregate"]),
]

METHODS = [
    {
        "key": "slag_ageing_crushing_screening",
        "name": "Slag ageing + crushing + screening",
        "description": "Open-yard weathering to hydrate free lime, then crushing and screening to 0–40 mm.",
        "input": "Steel Slag", "output": "Processed Slag Aggregate",
        "steps": ["ageing", "crushing", "screening"],
        "input_constraints": [
            {"property_key": "free_lime_pct", "max": 6, "importance": "REQUIRED"},
            {"property_key": "moisture_pct", "max": 15, "importance": "PREFERRED"},
        ],
        "output_properties": {"free_lime_pct": 0.8, "particle_size_mm": 40, "moisture_pct": 5},
        "expected_yield": 0.92, "processing_time_days": 45, "indicative_cost_per_tonne": 220,
        "quality": "Volume stability to be confirmed by expansion testing before use.",
    },
]


def seed_processing_knowledge(db: Session) -> None:
    """Idempotent upsert of processed products and processing methods."""
    apps = {a.key: a for a in db.scalars(select(ApplicationType))}
    materials = {m.canonical_name: m for m in db.scalars(select(Material))}
    for name, category, subcategory, state, description, synonyms, app_keys in PROCESSED_MATERIALS:
        material = materials.get(name) or Material(canonical_name=name)
        material.category, material.subcategory, material.physical_state = category, subcategory, state
        material.description, material.synonyms, material.is_processed = description, synonyms, True
        db.add(material)
        db.flush()
        materials[name] = material
        for key in app_keys:
            if key not in apps:
                continue
            exists = db.scalars(select(MaterialApplication).where(MaterialApplication.material_id == material.id,
                                                                  MaterialApplication.application_type_id == apps[key].id)).first()
            if exists is None:
                db.add(MaterialApplication(material_id=material.id, application_type_id=apps[key].id,
                                           description=f"{name} for {apps[key].name}.", required_properties=[]))
    for spec in METHODS:
        method = db.scalars(select(ProcessingMethod).where(ProcessingMethod.key == spec["key"])).first()
        method = method or ProcessingMethod(key=spec["key"])
        method.name, method.description = spec["name"], spec["description"]
        method.input_material_id = materials[spec["input"]].id
        method.output_material_id = materials[spec["output"]].id
        method.processing_steps, method.input_constraints = spec["steps"], spec["input_constraints"]
        method.output_properties, method.expected_yield = spec["output_properties"], spec["expected_yield"]
        method.processing_time_days = spec["processing_time_days"]
        method.indicative_cost_per_tonne = spec["indicative_cost_per_tonne"]
        method.quality_requirements, method.source_note = spec["quality"], DEMO_NOTE
        db.add(method)
    db.commit()
