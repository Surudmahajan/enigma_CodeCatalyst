"""Application discovery for a resource.

Curated knowledge first: the material's known applications, each checked
against its screening rules with the resource's confirmed values. Related
materials' applications are offered as lower-confidence leads. Optional model
ideas are limited to known application types and labelled UNVERIFIED — they
are never used by the matching engine.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import llm
from app.materials.models import ApplicationType, Material, MaterialApplication, PropertyDefinition
from app.matching.components import PropertyOutcome, evaluate_constraint
from app.matching.profiles import build_resource_profile
from app.matching.types import ConstraintSpec
from app.resources.models import Resource

PROMPT_VERSION = "applications-v1"


def _check_rules(profile, rules: list[dict], names: dict[str, tuple[str, str | None]]) -> tuple[str, list[str]]:
    status, evidence = "ELIGIBLE", []
    for rule in rules:
        name, unit = names.get(rule["property_key"], (rule["property_key"], None))
        spec = ConstraintSpec(rule["property_key"], name, unit, rule.get("min"), rule.get("max"), None,
                              rule.get("importance", "REQUIRED"))
        check = evaluate_constraint(spec, profile)
        evidence.append(f"{name}: {check.observed} (rule {check.constraint}, {check.importance.lower()})")
        if check.outcome == PropertyOutcome.FAIL and check.importance == "REQUIRED":
            status = "BLOCKED"
        elif check.outcome != PropertyOutcome.PASS and status == "ELIGIBLE" and check.importance == "REQUIRED":
            status = "NEEDS_DATA"
    return status, evidence


def discover(db: Session, resource: Resource) -> dict:
    profile = build_resource_profile(db, resource)
    names = {p.key: (p.name, p.unit) for p in db.scalars(select(PropertyDefinition))}
    curated, related = [], []
    material = resource.material
    if material is not None:
        for link in db.scalars(select(MaterialApplication).where(MaterialApplication.material_id == material.id)):
            status, evidence = _check_rules(profile, link.required_properties or [], names)
            curated.append({"application_key": link.application_type.key, "application": link.application_type.name,
                            "status": status, "evidence": evidence, "source_note": link.source_note,
                            "source": "KNOWLEDGE_BASE"})
        known = {c["application_key"] for c in curated}
        siblings = db.scalars(select(Material).where(Material.category == material.category,
                                                     Material.id != material.id))
        for sibling in siblings:
            for link in db.scalars(select(MaterialApplication).where(MaterialApplication.material_id == sibling.id)):
                if link.application_type.key in known:
                    continue
                known.add(link.application_type.key)
                related.append({"application_key": link.application_type.key,
                                "application": link.application_type.name, "status": "LEAD",
                                "evidence": [f"Known for the related material {sibling.canonical_name}; "
                                             "suitability for this resource is not established."],
                                "source": "RELATED_MATERIAL"})
    return {"curated": curated, "related": related, "ai_ideas": _model_ideas(db, resource, curated + related)}


def _model_ideas(db: Session, resource: Resource, already: list[dict]) -> list[dict]:
    if not llm.is_enabled():
        return []
    applications = {a.key: a for a in db.scalars(select(ApplicationType))}
    known = {a["application_key"] for a in already}
    values = ", ".join(f"{pv.property.name}={pv.value_numeric}" for pv in resource.property_values if pv.confirmed)
    result = llm.complete_json(
        feature="application_discovery", prompt_version=PROMPT_VERSION, subject_id=resource.id,
        system=("You suggest possible industrial uses for a by-product, choosing only from the given application "
                "list. Explain briefly why; say what data would confirm suitability."),
        prompt=(f"Applications: {', '.join(f'{k} ({a.name})' for k, a in applications.items())}\n\n"
                f"By-product: {resource.name}. {resource.description or ''} Material: "
                f"{resource.material.canonical_name if resource.material else 'unclassified'}. Measured: {values or 'none'}."),
        schema={"type": "object", "additionalProperties": False, "required": ["ideas"],
                "properties": {"ideas": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["application_key", "rationale"],
                    "properties": {"application_key": {"type": "string", "enum": list(applications)},
                                   "rationale": {"type": "string"}}}}}},
    )
    ideas = []
    for idea in (result or {}).get("ideas", [])[:5]:
        key = idea.get("application_key")
        if key in applications and key not in known:
            ideas.append({"application_key": key, "application": applications[key].name, "status": "UNVERIFIED",
                          "evidence": [str(idea.get("rationale", ""))[:300]], "source": "AI_MODEL"})
    if result is not None:
        llm.log_output("application_discovery", PROMPT_VERSION, resource.name, "ACCEPTED",
                       {"ideas": [i["application_key"] for i in ideas]}, resource.id)
    return ideas
