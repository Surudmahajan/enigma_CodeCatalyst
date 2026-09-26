"""Impact records for completed exchanges.

Reuses the matching engine's economic and environmental functions on the
delivered quantity, so there is exactly one implementation of each
calculation. Records say whether they are platform estimates, figures derived
from party-reported quantities, or verified outcomes.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.assessment.economic import assess_economics
from app.assessment.environmental import assess_environment
from app.audit import service as audit
from app.core.time import utcnow
from app.exchanges.models import Exchange, ExchangeStatus
from app.impact.models import ImpactRecord, ImpactSource, MetricType
from app.materials import units
from app.matching.engine import METHODOLOGY_VERSION
from app.matching.geo import haversine_km
from app.matching.profiles import build_requirement_profile, build_resource_profile
from app.matching.service import active_parameters, resolve_factors

METHOD = "symbio.impact.exchange"


def _months_between(start: date, end: date) -> float:
    return max(0.0, (end - start).days / units.DAYS_PER_MONTH)


def delivered_base_quantity(exchange: Exchange) -> tuple[float, ImpactSource, list[str]]:
    """Total delivered quantity in base units, with its provenance."""
    if exchange.delivered_quantity is not None:
        return (units.to_base(float(exchange.delivered_quantity), exchange.unit), ImpactSource.USER_INPUT,
                ["Delivered quantity reported by the parties at completion."])
    agreed = units.to_base(float(exchange.agreed_quantity), exchange.unit)
    if exchange.agreed_frequency == units.Frequency.ONE_TIME:
        return agreed, ImpactSource.SYSTEM_ESTIMATE, ["Estimated from the agreed one-time quantity."]
    start = (exchange.started_at.date() if exchange.started_at else exchange.start_date)
    end = exchange.completed_at.date() if exchange.completed_at else (exchange.end_date or start)
    months = max(_months_between(start, end), 1 / units.DAYS_PER_MONTH)
    monthly = agreed * units.PER_MONTH_FACTOR[exchange.agreed_frequency]
    return (monthly * months, ImpactSource.SYSTEM_ESTIMATE,
            [f"Estimated as the agreed rate over {months:.1f} months of operation (no delivered quantity reported)."])


def record_for_exchange(db: Session, exchange_id: uuid.UUID) -> list[ImpactRecord]:
    exchange = db.get(Exchange, exchange_id)
    if exchange is None or exchange.status != ExchangeStatus.COMPLETED:
        return []
    match = exchange.match
    resource, requirement = match.resource, match.requirement
    rp, qp = build_resource_profile(db, resource), build_requirement_profile(requirement)
    params = active_parameters(db)
    factors = resolve_factors(db, rp, qp, requirement.intended_application_id)
    quantity, source, notes = delivered_base_quantity(exchange)
    base_unit = units.base_unit(exchange.unit).value
    distance = haversine_km(rp.location, qp.location) if rp.location and qp.location else None
    economic = assess_economics(rp, qp, quantity, base_unit, "total", distance, params)
    environmental = assess_environment(rp, quantity, base_unit, "total", distance, rp.processing_required, factors,
                                       params)
    inputs = {"quantity": round(quantity, 3), "unit": base_unit, "distance_km": round(distance, 1) if distance else None,
              "factor_ids": [f.id for f in environmental.factors_used], "matching_version": params.version,
              "economic_method": f"{economic.method}@{economic.version}",
              "environmental_method": f"{environmental.method}@{environmental.version}"}

    # Re-running replaces earlier unverified figures; verified outcomes are never overwritten.
    db.execute(delete(ImpactRecord).where(ImpactRecord.exchange_id == exchange.id,
                                          ImpactRecord.source_type != ImpactSource.VERIFIED_OUTCOME))
    records: list[ImpactRecord] = []

    def add(metric: MetricType, value: float | None, unit: str, extra: list[str], demo: bool = False) -> None:
        if value is None:
            return
        records.append(ImpactRecord(
            exchange_id=exchange.id, match_id=match.id, provider_org_id=exchange.provider_org_id,
            demander_org_id=exchange.demander_org_id, metric_type=metric, value=Decimal(str(round(value, 3))),
            unit=unit, calculation_method=METHOD, methodology_version=METHODOLOGY_VERSION, source_type=source,
            uses_demo_factors=demo, assumptions=notes + extra, inputs=inputs,
        ))

    env_notes = environmental.assumptions
    demo = environmental.uses_demo_factors
    if units.unit_family(exchange.unit) == units.UnitFamily.ENERGY:
        add(MetricType.ENERGY_RECOVERED, quantity, base_unit, env_notes)
    else:
        add(MetricType.WASTE_DIVERTED, environmental.waste_diverted, base_unit, env_notes)
        add(MetricType.VIRGIN_MATERIAL_AVOIDED, environmental.virgin_material_avoided, base_unit, env_notes)
    add(MetricType.TRANSPORT_EMISSIONS, environmental.transport_kgco2e, "kgCO2e", env_notes, demo)
    if environmental.processing_kgco2e:
        add(MetricType.PROCESSING_EMISSIONS, environmental.processing_kgco2e, "kgCO2e", env_notes, demo)
    add(MetricType.NET_CO2E, environmental.net_benefit_kgco2e, "kgCO2e", env_notes, demo)
    add(MetricType.ECONOMIC_VALUE, economic.net_value, economic.currency, economic.assumptions + economic.notes)
    db.add_all(records)
    audit.record(db, action="IMPACT_RECORDED", entity_type="exchange", entity_id=exchange.id,
                 details={"records": len(records), "source": source})
    db.commit()
    return records


def verify_exchange_impact(db: Session, exchange_id: uuid.UUID, verifier_id: uuid.UUID) -> int:
    records = list(db.scalars(select(ImpactRecord).where(ImpactRecord.exchange_id == exchange_id)))
    for record in records:
        record.source_type = ImpactSource.VERIFIED_OUTCOME
        record.verified_by_user_id, record.verified_at = verifier_id, utcnow()
    audit.record(db, action="IMPACT_VERIFIED", entity_type="exchange", entity_id=exchange_id, actor_user_id=verifier_id,
                 details={"records": len(records)})
    db.commit()
    return len(records)
