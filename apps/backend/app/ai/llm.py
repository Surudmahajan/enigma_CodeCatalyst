"""Provider-agnostic LLM adapter (Claude via the official Anthropic SDK).

Rules enforced here and by every caller:
  * The platform works fully with AI_PROVIDER=none; callers fall back to deterministic logic.
  * Outputs are requested as JSON matching a schema (structured outputs) and are
    *suggestions*: callers validate them against the knowledge base and input facts
    before anything is stored, and never let them change quantities, verification
    status, factors or match decisions.
  * Every call is logged (model, prompt version, input hash, validation outcome).
"""

import hashlib
import json
import logging
import uuid
from typing import Any

import anthropic

from app.ai.models import AIOutputLog
from app.core.config import get_settings
from app.core.database import SessionLocal

logger = logging.getLogger("symbio.ai")

FALLBACK_BETA = "server-side-fallback-2026-07-01"
_client: anthropic.Anthropic | None = None


def is_enabled() -> bool:
    return get_settings().ai_provider == "anthropic"


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        settings = get_settings()
        # With no AI_API_KEY the SDK resolves credentials from ANTHROPIC_API_KEY / an `ant` profile.
        _client = anthropic.Anthropic(api_key=settings.ai_api_key or None, timeout=60.0, max_retries=2)
    return _client


def log_output(feature: str, prompt_version: str, input_text: str, status: str, output: Any = None,
               subject_id: uuid.UUID | None = None) -> None:
    settings = get_settings()
    try:
        with SessionLocal() as db:
            db.add(AIOutputLog(feature=feature, provider=settings.ai_provider, model=settings.ai_model,
                               prompt_version=prompt_version, status=status, subject_id=subject_id,
                               input_sha256=hashlib.sha256(input_text.encode()).hexdigest(),
                               output=output if isinstance(output, dict) else {"value": output}))
            db.commit()
    except Exception:  # logging must never break the calling feature
        logger.warning("Could not write AI output log", exc_info=True)


def complete_json(*, feature: str, prompt_version: str, system: str, prompt: str, schema: dict[str, Any],
                  subject_id: uuid.UUID | None = None, max_tokens: int = 4096) -> dict[str, Any] | None:
    """Return the model's JSON object, or None when AI is disabled, refused or failed."""
    if not is_enabled():
        return None
    settings = get_settings()
    try:
        response = _get_client().beta.messages.create(
            model=settings.ai_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            # Route safety-classifier refusals to an appropriate fallback model automatically.
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
    except anthropic.RateLimitError:
        logger.warning("AI rate limited for %s", feature)
        log_output(feature, prompt_version, prompt, "ERROR", {"error": "rate_limited"}, subject_id)
        return None
    except anthropic.APIStatusError as exc:
        logger.warning("AI API error %s for %s", exc.status_code, feature)
        log_output(feature, prompt_version, prompt, "ERROR", {"error": f"status_{exc.status_code}"}, subject_id)
        return None
    except anthropic.APIConnectionError:
        logger.warning("AI connection error for %s", feature)
        log_output(feature, prompt_version, prompt, "ERROR", {"error": "connection"}, subject_id)
        return None

    if response.stop_reason == "refusal":
        log_output(feature, prompt_version, prompt, "REFUSED", None, subject_id)
        return None
    if response.stop_reason == "max_tokens":
        log_output(feature, prompt_version, prompt, "ERROR", {"error": "max_tokens"}, subject_id)
        return None
    text = next((b.text for b in response.content if b.type == "text"), None)
    try:
        data = json.loads(text) if text else None
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        log_output(feature, prompt_version, prompt, "ERROR", {"error": "invalid_json"}, subject_id)
        return None
    return data
