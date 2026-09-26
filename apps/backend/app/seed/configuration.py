"""Default matching configuration and environmental factors.

The emission factors seeded here are ILLUSTRATIVE DEMO VALUES. They are
stored with ``is_demo_value=True`` and every assessment that uses them says
so. Replace them through the admin console with sourced, region-specific
factors (e.g. national GHG conversion factors or an LCA database) before
relying on any CO2e figure.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assessment.models import EmissionFactor, FactorScope
from app.materials.models import ApplicationType, Material
from app.matching.models import MatchingConfig

DEFAULT_WEIGHTS = {
    "material": 0.30, "quantity": 0.20, "location": 0.15, "timing": 0.10,
    "processing": 0.10, "economic": 0.10, "environmental": 0.05,
}

DEFAULT_PARAMETERS = {
    "default_max_distance_km": 300,
    "candidate_radius_km": 2500,
    "open_ended_horizon_days": 365,
    "min_overall_score": 0.35,
    "semantic_candidate_threshold": 0.35,
    "semantic_only_score_cap": 0.60,
    "blocker_score_cap": 0.55,
    "quantity_supply_utilization_weight": 0.30,
    "importance_weights": {"REQUIRED": 1.0, "PREFERRED": 0.6, "OPTIONAL": 0.3},
    # Demo freight assumption for economic screening only; flagged in every result.
    "transport_cost_per_tonne_km": 4.0,
    "transport_cost_currency": "INR",
    "transport_cost_is_demo": True,
    "substitution_ratio": 1.0,
    "match_ttl_days": 30,
}

DEMO_SOURCE = "SYMBIO illustrative demo dataset — not taken from a verified source."
DEMO_METHOD = ("Illustrative screening value for demonstrating the calculation. Replace with a sourced, "
               "region-specific factor before use.")

# key, scope, unit, value, selector (material name / application key / disposition)
DEMO_FACTORS = [
    ("transport.road.truck", FactorScope.TRANSPORT, "kgCO2e/t-km", 0.10, {}),
    ("virgin.natural_aggregate", FactorScope.VIRGIN_PRODUCTION, "kgCO2e/t", 5.0, {"material": "Natural Aggregate"}),
    ("virgin.road_subbase", FactorScope.VIRGIN_PRODUCTION, "kgCO2e/t", 5.0, {"application": "road_subbase"}),
    ("virgin.concrete_aggregate", FactorScope.VIRGIN_PRODUCTION, "kgCO2e/t", 5.0, {"application": "concrete_aggregate"}),
    ("virgin.cement_clinker", FactorScope.VIRGIN_PRODUCTION, "kgCO2e/t", 800.0, {"application": "cement_blending"}),
    ("virgin.limestone", FactorScope.VIRGIN_PRODUCTION, "kgCO2e/t", 8.0, {"material": "Limestone"}),
    ("virgin.brick_clay", FactorScope.VIRGIN_PRODUCTION, "kgCO2e/t", 10.0, {"application": "brick_making"}),
    ("virgin.natural_gypsum", FactorScope.VIRGIN_PRODUCTION, "kgCO2e/t", 10.0, {"application": "cement_set_retarder"}),
    ("disposal.landfill.inert", FactorScope.DISPOSAL, "kgCO2e/t", 1.5, {"disposition": "DISPOSAL"}),
    ("disposal.stockpile", FactorScope.DISPOSAL, "kgCO2e/t", 0.5, {"disposition": "STORAGE"}),
    ("processing.crushing_screening", FactorScope.PROCESSING, "kgCO2e/t", 2.0, {}),
]


def seed_matching_config(db: Session) -> MatchingConfig:
    config = db.scalars(select(MatchingConfig).where(MatchingConfig.version == "1.0")).first()
    if config is None:
        config = MatchingConfig(version="1.0", weights=DEFAULT_WEIGHTS, parameters=DEFAULT_PARAMETERS,
                                description="Baseline weights from the SYMBIO technical specification.")
        db.add(config)
    if not db.scalars(select(MatchingConfig).where(MatchingConfig.is_active.is_(True))).first():
        config.is_active = True
    db.commit()
    return config


def seed_demo_emission_factors(db: Session) -> int:
    materials = {m.canonical_name: m.id for m in db.scalars(select(Material))}
    applications = {a.key: a.id for a in db.scalars(select(ApplicationType))}
    existing = {f.key for f in db.scalars(select(EmissionFactor))}
    created = 0
    for key, scope, unit, value, selector in DEMO_FACTORS:
        if key in existing:
            continue
        db.add(EmissionFactor(
            key=key, scope=scope, unit=unit, value=value,
            material_id=materials.get(selector.get("material", "")),
            application_type_id=applications.get(selector.get("application", "")),
            disposition=selector.get("disposition"), source=DEMO_SOURCE, geography="Demo (India context)",
            methodology=DEMO_METHOD, version="demo-1", valid_from=date(2024, 1, 1), is_demo_value=True,
        ))
        created += 1
    db.commit()
    return created
