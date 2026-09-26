"""Material classification: free text -> ranked canonical-material *suggestions*.

Deterministic first (names, synonyms, categories, embeddings over the knowledge
base). The optional model re-rank can only choose among existing material ids;
anything else is discarded. Nothing is applied until the user confirms it.
"""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import llm
from app.ai.embeddings import cosine, embed
from app.materials.models import Material

PROMPT_VERSION = "classify-v1"
_WORD = re.compile(r"[a-z0-9]+")


def _material_text(m: Material) -> str:
    return " ".join([m.canonical_name, m.category, m.subcategory or "", " ".join(m.synonyms or []), m.description or ""])


def _phrase_in(phrase: str, text: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase.lower())}(?![a-z0-9])", text) is not None


def classify(db: Session, text: str, limit: int = 5) -> list[dict]:
    lowered = text.lower()
    words = set(_WORD.findall(lowered))
    query_vec = embed(text)
    scored: dict[uuid.UUID, dict] = {}
    for material in db.scalars(select(Material).where(Material.is_active.is_(True))):
        reasons: list[str] = []
        score = 0.0
        names = [material.canonical_name, *(material.synonyms or [])]
        hit = next((n for n in sorted(names, key=len, reverse=True) if _phrase_in(n, lowered)), None)
        if hit:
            score = max(score, 0.9 if hit.lower() == material.canonical_name.lower() else 0.85)
            reasons.append(f"Mentions “{hit}”")
        category_words = set(_WORD.findall(f"{material.category} {material.subcategory or ''}".lower())) - {"residue"}
        overlap = words & category_words
        if overlap:
            score = max(score, min(0.5, 0.2 + 0.1 * len(overlap)))
            reasons.append(f"Category terms: {', '.join(sorted(overlap))}")
        similarity = cosine(query_vec, embed(_material_text(material))) or 0.0
        if similarity > 0.2:
            score = max(score, min(0.7, similarity))
            reasons.append(f"Description similarity {similarity:.0%}")
        if score >= 0.2:
            scored[material.id] = {"material": material, "confidence": round(score, 3), "reasons": reasons,
                                   "source": "KNOWLEDGE_BASE" if hit or overlap else "SEMANTIC"}

    ranked = sorted(scored.values(), key=lambda s: s["confidence"], reverse=True)[:limit]
    _model_rerank(db, text, ranked)
    return sorted(ranked, key=lambda s: s["confidence"], reverse=True)[:limit]


def _model_rerank(db: Session, text: str, ranked: list[dict]) -> None:
    """Optional: let the model add or re-weight candidates, restricted to known material ids."""
    if not llm.is_enabled():
        return
    catalogue = {str(m.id): m for m in db.scalars(select(Material).where(Material.is_active.is_(True)))}
    listing = "\n".join(f"{mid}: {m.canonical_name} ({m.category}; also known as {', '.join(m.synonyms[:5])})"
                        for mid, m in catalogue.items())
    result = llm.complete_json(
        feature="material_classification", prompt_version=PROMPT_VERSION,
        system=("You classify industrial by-products and raw materials into a fixed catalogue. Choose only ids "
                "from the catalogue. If nothing fits, return an empty list."),
        prompt=f"Catalogue:\n{listing}\n\nDescription to classify:\n{text}",
        schema={"type": "object", "additionalProperties": False, "required": ["suggestions"],
                "properties": {"suggestions": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["material_id", "confidence", "reason"],
                    "properties": {"material_id": {"type": "string", "enum": list(catalogue)},
                                   "confidence": {"type": "number"}, "reason": {"type": "string"}}}}}},
    )
    if not result:
        return
    accepted = []
    by_id = {str(s["material"].id): s for s in ranked}
    for item in result.get("suggestions", [])[:5]:
        material = catalogue.get(str(item.get("material_id")))
        if material is None:  # validation: unknown ids are discarded
            continue
        confidence = max(0.0, min(0.95, float(item.get("confidence", 0))))
        reason = str(item.get("reason", ""))[:200]
        entry = by_id.get(str(material.id))
        if entry:
            entry["confidence"] = round(max(entry["confidence"], confidence), 3)
            entry["reasons"].append(f"AI: {reason}")
        else:
            ranked.append({"material": material, "confidence": round(confidence, 3), "reasons": [f"AI: {reason}"],
                           "source": "AI_MODEL"})
        accepted.append(str(material.id))
    llm.log_output("material_classification", PROMPT_VERSION, text, "ACCEPTED", {"accepted_ids": accepted})
