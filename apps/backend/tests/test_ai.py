"""AI assistance: deterministic defaults, human confirmation, and guardrails against model output."""

import pytest
from sqlalchemy import select

from app.ai import explanations, llm
from app.ai.models import AIOutputLog
from tests.test_connections_messaging import matched
from tests.test_matching_api import create_need, create_slag, provider_and_demander

SPEC_SHEET = b"""XRF analysis - GBFS lot 42
SiO2: 34.5 %
CaO 39,2 %
MgO = 8.1%
Moisture content: 7 %
Blaine fineness 380 m2/kg
"""


@pytest.fixture
def fake_llm(monkeypatch):
    """Enable the AI path with a scripted model response per feature."""
    responses: dict[str, dict] = {}
    monkeypatch.setattr(llm, "is_enabled", lambda: True)

    def fake_complete_json(*, feature, **_kwargs):
        return responses.get(feature)

    monkeypatch.setattr(llm, "complete_json", fake_complete_json)
    return responses


def test_ai_status_reports_deterministic_default(client, kb):
    abc, _xyz = provider_and_demander(client)
    status = abc.get("/ai/status").json()
    assert status["llm_enabled"] is False and status["embedding_model"] == "symbio-hash-v1"


def test_classification_suggests_without_applying(client, kb):
    abc, _xyz = provider_and_demander(client)
    result = abc.post("/materials/classify", json={"text": "Water quenched GGBS from our blast furnace"}).json()
    top = result["suggestions"][0]
    assert top["material"]["canonical_name"] == "Granulated Blast Furnace Slag"
    assert top["source"] == "KNOWLEDGE_BASE" and top["confidence"] >= 0.8
    assert "Confirm" in result["note"]


def test_model_classification_cannot_invent_materials(client, kb, fake_llm):
    fake_llm["material_classification"] = {"suggestions": [
        {"material_id": "00000000-0000-0000-0000-000000000000", "confidence": 0.99, "reason": "made up"},
        {"material_id": kb.material("Fly Ash"), "confidence": 0.7, "reason": "pozzolanic ash"},
    ]}
    abc, _xyz = provider_and_demander(client)
    names = [s["material"]["canonical_name"] for s in
             abc.post("/materials/classify", json={"text": "grey powder from ESP hoppers"}).json()["suggestions"]]
    assert "Fly Ash" in names and len(names) == len(set(names))


def _upload_spec(api, resource_id, data=SPEC_SHEET):
    return api.post("/documents", files={"file": ("spec.txt", data, "text/plain")},
                    data={"resource_id": resource_id}).json()


def test_document_extraction_creates_unconfirmed_suggestions(client, kb):
    abc, xyz = provider_and_demander(client)
    resource = create_slag(abc, kb, material_id=kb.material("Granulated Blast Furnace Slag"),
                           name="Granulated slag", properties=[{"property_key": "moisture_pct", "value_numeric": 6}])
    doc = _upload_spec(abc, resource["id"])
    result = abc.post(f"/documents/{doc['id']}/extract", json={"resource_id": resource["id"]}).json()
    values = {s["property_key"]: float(s["value"]) for s in result["suggestions"]}
    assert values == {"sio2_pct": 34.5, "cao_pct": 39.2, "mgo_pct": 8.1, "fineness_m2kg": 380}
    # The user's own moisture value is never overwritten.
    assert result["skipped"][0]["property_key"] == "moisture_pct"
    props = {p["property_key"]: p for p in abc.get(f"/resources/{resource['id']}").json()["properties"]}
    assert props["sio2_pct"]["source"] == "AI_EXTRACTED" and props["sio2_pct"]["confirmed"] is False
    assert props["moisture_pct"]["source"] == "USER_INPUT" and float(props["moisture_pct"]["value_numeric"]) == 6


def test_unconfirmed_values_do_not_affect_matching_until_confirmed(client, kb):
    abc, xyz = provider_and_demander(client)
    resource = create_slag(abc, kb, properties=[{"property_key": "moisture_pct", "value_numeric": 6}])
    create_need(xyz, kb, property_constraints=[{"property_key": "sio2_pct", "min_value": 30, "importance": "REQUIRED"}])
    detail_id = abc.get("/matches").json()[0]["id"]
    before = abc.get(f"/matches/{detail_id}").json()["explanation"]["property_checks"][0]
    assert before["measured"] is False
    doc = _upload_spec(abc, resource["id"])
    abc.post(f"/documents/{doc['id']}/extract", json={"resource_id": resource["id"]})
    still = abc.get(f"/matches/{detail_id}").json()["explanation"]["property_checks"][0]
    assert still["measured"] is False  # unconfirmed AI value ignored
    value = next(p for p in abc.get(f"/resources/{resource['id']}").json()["properties"] if p["property_key"] == "sio2_pct")
    abc.post(f"/resources/{resource['id']}/properties/{value['id']}/confirm", json={"accept": True})
    after = abc.get(f"/matches/{detail_id}").json()["explanation"]["property_checks"][0]
    assert after["measured"] is True and after["outcome"] == "PASS"


def test_model_extraction_requires_quoted_evidence(client, kb, fake_llm):
    fake_llm["document_extraction"] = {"values": [
        {"property_key": "loi_pct", "value": 2.1, "snippet": "LOI 2.1 %"},        # not in the document: rejected
        {"property_key": "al2o3_pct", "value": 150, "snippet": "SiO2: 34.5 %"},   # implausible range: rejected
        {"property_key": "sio2_pct", "value": 34.5, "snippet": "SiO2: 34.5 %"},   # agrees with pattern extraction
    ]}
    abc, _xyz = provider_and_demander(client)
    resource = create_slag(abc, kb, properties=[])
    doc = _upload_spec(abc, resource["id"])
    result = abc.post(f"/documents/{doc['id']}/extract", json={"resource_id": resource["id"]}).json()
    keys = {s["property_key"]: s for s in result["suggestions"]}
    assert "loi_pct" not in keys and "al2o3_pct" not in keys
    assert keys["sio2_pct"]["confidence"] == 0.9  # two methods agree
    assert any("failed validation" in n for n in result["notes"])


def test_application_discovery_checks_rules(client, kb):
    abc, _xyz = provider_and_demander(client)
    resource = create_slag(abc, kb)
    result = abc.get(f"/resources/{resource['id']}/application-suggestions").json()
    statuses = {a["application_key"]: a["status"] for a in result["curated"]}
    assert statuses["road_subbase"] == "ELIGIBLE"      # free lime 2.5 <= 4
    assert statuses["concrete_aggregate"] == "BLOCKED"  # free lime 2.5 > 2
    assert all(a["status"] == "LEAD" for a in result["related"])
    assert result["ai_ideas"] == []


def test_ai_summary_unavailable_without_provider(client, kb):
    abc, _xyz, match_id = matched(client, kb)
    assert abc.post(f"/matches/{match_id}/ai-summary").json()["status"] == "UNAVAILABLE"


def test_ai_summary_rejects_invented_figures_and_keeps_facts(client, kb, fake_llm, db):
    abc, _xyz, match_id = matched(client, kb)
    fake_llm["match_explanation"] = {"summary": "This exchange saves 5,000,000 rupees a year guaranteed."}
    rejected = abc.post(f"/matches/{match_id}/ai-summary").json()
    assert rejected["status"] == "REJECTED"
    fake_llm["match_explanation"] = {"summary": "A potential opportunity: ABC Steel's slag could meet all of XYZ "
                                                "Construction's 1,500 t/month need from about 82 km away."}
    accepted = abc.post(f"/matches/{match_id}/ai-summary").json()
    assert accepted["status"] == "GENERATED"
    detail = abc.get(f"/matches/{match_id}").json()["explanation"]
    assert detail["ai_summary"]["prompt_version"] == explanations.PROMPT_VERSION
    assert detail["summary"].startswith("ABC Steel's Steel Slag")  # deterministic summary untouched
    statuses = [log.status for log in db.scalars(select(AIOutputLog))]
    assert "REJECTED_VALIDATION" in statuses and "ACCEPTED" in statuses


def test_number_guard():
    facts = '{"summary": "Supply 2,000 t/month, demand 1,500 t/month, 82 km, 75%"}'
    assert explanations.unsupported_numbers("Uses 75% of 2000 t over 82 km", facts) == set()
    assert explanations.unsupported_numbers("Saves 40% of costs", facts) == {"40"}
