"""Optional AI rewording of a match summary, with a fact guard.

The model receives only the structured, deterministic explanation. Its output
is rejected if it contains any number that does not appear in those facts,
and it is stored separately (``explanation.ai_summary``) with model and prompt
version — the deterministic summary is never replaced.
"""

import json
import re

from sqlalchemy.orm import Session

from app.ai import llm
from app.core.config import get_settings
from app.core.time import utcnow
from app.matching.models import Match

PROMPT_VERSION = "explain-v1"
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip("0").rstrip(".") if "." in n else n.replace(",", "") for n in _NUM.findall(text)}


def unsupported_numbers(candidate: str, facts: str) -> set[str]:
    return _numbers(candidate) - _numbers(facts)


def generate(db: Session, match: Match) -> dict:
    explanation = match.explanation or {}
    facts = {k: explanation.get(k) for k in ("summary", "strengths", "considerations", "feasibility")}
    facts["components"] = {k: v.get("headline") for k, v in (explanation.get("components") or {}).items()}
    facts_text = json.dumps(facts, ensure_ascii=False)
    if not llm.is_enabled():
        return {"status": "UNAVAILABLE", "reason": "No AI provider is configured; the standard explanation applies."}
    result = llm.complete_json(
        feature="match_explanation", prompt_version=PROMPT_VERSION, subject_id=match.id, max_tokens=1024,
        system=("Rewrite industrial symbiosis match facts as a clear 2-4 sentence summary for a plant manager. "
                "Use only the facts given. Do not add numbers, claims, guarantees or recommendations that are not "
                "in the facts. Call it a potential opportunity."),
        prompt=f"Facts (JSON):\n{facts_text}",
        schema={"type": "object", "additionalProperties": False, "required": ["summary"],
                "properties": {"summary": {"type": "string"}}},
    )
    if not result or not str(result.get("summary", "")).strip():
        return {"status": "UNAVAILABLE", "reason": "The AI service did not return a usable summary."}
    summary = str(result["summary"]).strip()[:1200]
    extra = unsupported_numbers(summary, facts_text)
    if extra:
        llm.log_output("match_explanation", PROMPT_VERSION, facts_text, "REJECTED_VALIDATION",
                       {"unsupported_numbers": sorted(extra)}, match.id)
        return {"status": "REJECTED", "reason": "The AI summary contained figures not present in the assessment."}
    ai_summary = {"text": summary, "model": get_settings().ai_model, "prompt_version": PROMPT_VERSION,
                  "generated_at": utcnow().isoformat(), "label": "AI-generated wording of the assessment above"}
    match.explanation = {**explanation, "ai_summary": ai_summary}  # new dict so the JSON change is persisted
    db.commit()
    llm.log_output("match_explanation", PROMPT_VERSION, facts_text, "ACCEPTED", ai_summary, match.id)
    return {"status": "GENERATED", "ai_summary": ai_summary}
