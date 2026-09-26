"""Document extraction: specification sheets / test reports -> property value *suggestions*.

Pipeline:  document text -> deterministic pattern extraction (+ optional model
extraction) -> validation (known property, plausible range, and for model
output the quoted snippet must literally occur in the document) -> stored as
AI_EXTRACTED, *unconfirmed* values with provenance. Unconfirmed values are
ignored by matching until a user confirms them, and user-entered values are
never overwritten.
"""

import io
import re
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import llm
from app.common.listings import ValueSource
from app.materials.models import PropertyDataType, PropertyDefinition
from app.resources.models import Resource, ResourcePropertyValue

PROMPT_VERSION = "extract-v1"
MAX_MODEL_CHARS = 60_000
_NUMBER = r"(-?\d+(?:[.,]\d+)?)"


@dataclass
class Extracted:
    property_key: str
    value: Decimal
    snippet: str
    method: str          # PATTERN | AI_MODEL
    confidence: float


@dataclass
class ExtractionResult:
    text_chars: int
    method: str
    suggestions: list[Extracted] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def extract_text(data: bytes, file_type: str) -> str:
    if file_type == "application/pdf":
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if file_type.endswith("wordprocessingml.document"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", "ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml)
    if file_type.startswith("text/"):
        return data.decode("utf-8", "ignore")
    return ""


def _to_decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None


def _in_range(definition: PropertyDefinition, value: Decimal) -> bool:
    return ((definition.valid_min is None or value >= definition.valid_min)
            and (definition.valid_max is None or value <= definition.valid_max))


def _pattern_extract(text: str, definitions: list[PropertyDefinition]) -> list[Extracted]:
    found: list[Extracted] = []
    for definition in definitions:
        labels = sorted({definition.name, definition.key.replace("_", " "), *(definition.aliases or [])},
                        key=len, reverse=True)
        for label in labels:
            pattern = rf"(?<![A-Za-z0-9]){re.escape(label)}(?![A-Za-z0-9])[^0-9\n\-]{{0,25}}?{_NUMBER}"
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            value = _to_decimal(match.group(1))
            if value is not None and _in_range(definition, value):
                found.append(Extracted(definition.key, value, match.group(0).strip()[:120], "PATTERN", 0.7))
                break
    return found


def _model_extract(text: str, definitions: list[PropertyDefinition], notes: list[str]) -> list[Extracted]:
    if not llm.is_enabled() or not text.strip():
        return []
    if len(text) > MAX_MODEL_CHARS:
        notes.append(f"Only the first {MAX_MODEL_CHARS:,} characters were sent for AI extraction.")
    excerpt = text[:MAX_MODEL_CHARS]
    by_key = {d.key: d for d in definitions}
    catalogue = "\n".join(f"{d.key}: {d.name} [{d.unit or 'unitless'}]" for d in definitions)
    result = llm.complete_json(
        feature="document_extraction", prompt_version=PROMPT_VERSION,
        system=("You extract measured material properties from industrial test reports. Report only values that "
                "are explicitly stated in the document, in the unit listed, and quote the exact text you read "
                "them from. Do not estimate or convert values."),
        prompt=f"Properties you may report:\n{catalogue}\n\nDocument:\n{excerpt}",
        schema={"type": "object", "additionalProperties": False, "required": ["values"],
                "properties": {"values": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["property_key", "value", "snippet"],
                    "properties": {"property_key": {"type": "string", "enum": list(by_key)},
                                   "value": {"type": "number"}, "snippet": {"type": "string"}}}}}},
    )
    if not result:
        return []
    accepted, rejected = [], 0
    normalized_text = re.sub(r"\s+", " ", excerpt).lower()
    for item in result.get("values", []):
        definition = by_key.get(item.get("property_key"))
        snippet = re.sub(r"\s+", " ", str(item.get("snippet", ""))).strip()
        value = _to_decimal(str(item.get("value")))
        # Validation: known key, plausible range, and the quoted evidence must exist in the document.
        if (definition is None or value is None or not _in_range(definition, value) or not snippet
                or snippet.lower() not in normalized_text):
            rejected += 1
            continue
        accepted.append(Extracted(definition.key, value, snippet[:120], "AI_MODEL", 0.8))
    llm.log_output("document_extraction", PROMPT_VERSION, excerpt, "ACCEPTED" if accepted else "REJECTED_VALIDATION",
                   {"accepted": len(accepted), "rejected": rejected})
    if rejected:
        notes.append(f"{rejected} AI-proposed value(s) failed validation and were discarded.")
    return accepted


def extract_for_resource(db: Session, resource: Resource, document_id, data: bytes, file_type: str) -> ExtractionResult:
    definitions = list(db.scalars(select(PropertyDefinition).where(
        PropertyDefinition.data_type == PropertyDataType.NUMERIC)))
    text = extract_text(data, file_type)
    result = ExtractionResult(text_chars=len(text), method="PATTERN")
    if not text.strip():
        result.notes.append("No machine-readable text found (scanned images need OCR, which is not enabled).")
        return result
    candidates = {e.property_key: e for e in _pattern_extract(text, definitions)}
    model_values = _model_extract(text, definitions, result.notes)
    if model_values:
        result.method = "PATTERN+AI_MODEL"
    for extracted in model_values:
        current = candidates.get(extracted.property_key)
        if current is None:
            candidates[extracted.property_key] = extracted
        elif current.value == extracted.value:
            current.confidence = 0.9  # two independent methods agree
    by_id = {d.key: d for d in definitions}
    existing = {pv.property.key: pv for pv in resource.property_values}
    for key, extracted in candidates.items():
        prior = existing.get(key)
        if prior is not None and (prior.source == ValueSource.USER_INPUT or prior.confirmed):
            result.skipped.append({"property_key": key, "reason": "A confirmed value already exists.",
                                   "extracted_value": str(extracted.value)})
            continue
        if prior is not None:
            resource.property_values.remove(prior)
            db.flush()
        resource.property_values.append(ResourcePropertyValue(
            property_id=by_id[key].id, value_numeric=extracted.value, source=ValueSource.AI_EXTRACTED,
            confirmed=False, confidence=extracted.confidence,
            provenance={"document_id": str(document_id), "method": extracted.method, "snippet": extracted.snippet,
                        "prompt_version": PROMPT_VERSION if extracted.method == "AI_MODEL" else None},
        ))
        result.suggestions.append(extracted)
    db.commit()
    return result
