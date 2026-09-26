"""Connection gating, private messaging (REST + WebSocket), documents and exchanges."""

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.conftest import Api, make_org, register_user
from tests.test_matching_api import create_need, create_slag, provider_and_demander

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def matched(client, kb):
    abc, xyz = provider_and_demander(client)
    create_slag(abc, kb)
    create_need(xyz, kb)
    match_id = abc.get("/matches").json()[0]["id"]
    return abc, xyz, match_id


def connected(client, kb):
    abc, xyz, match_id = matched(client, kb)
    connection = abc.post(f"/matches/{match_id}/connection-request", json={"message": "Interested in supplying"}).json()
    accepted = xyz.post(f"/connections/{connection['id']}/accept").json()
    return abc, xyz, match_id, accepted


# --- Connections ------------------------------------------------------------------------------

def test_connection_request_and_acceptance_opens_private_channel(client, kb):
    abc, xyz, match_id = matched(client, kb)
    response = abc.post(f"/matches/{match_id}/connection-request", json={"message": "Interested in supplying"})
    assert response.status_code == 201
    connection = response.json()
    assert connection["status"] == "PENDING" and connection["direction"] == "outgoing"
    assert abc.get(f"/matches/{match_id}").json()["status"] == "CONNECTION_REQUESTED"

    incoming = xyz.get("/connections", params={"direction": "incoming"}).json()
    assert len(incoming) == 1 and incoming[0]["can_respond"] is True
    # The requester cannot accept its own request.
    own = abc.post(f"/connections/{connection['id']}/accept")
    assert own.status_code == 403 and own.json()["error"]["code"] == "NOT_RECIPIENT"

    accepted = xyz.post(f"/connections/{connection['id']}/accept").json()
    assert accepted["status"] == "ACCEPTED" and accepted["conversation_id"]
    detail = abc.get(f"/matches/{match_id}").json()
    assert detail["status"] == "CONNECTED"
    assert "OPEN_CHAT" in detail["allowed_actions"] and "CREATE_EXCHANGE" in detail["allowed_actions"]
    messages = abc.get(f"/conversations/{accepted['conversation_id']}/messages").json()
    assert messages[0]["message_type"] == "SYSTEM"


def test_private_details_revealed_only_after_connection(client, kb):
    abc, xyz, match_id, _ = connected(client, kb)
    detail = xyz.get(f"/matches/{match_id}").json()
    assert detail["counterpart_contact"]["legal_name"] == "ABC Steel Pvt Ltd"
    assert detail["counterpart_contact"]["facility_location"]["latitude"] is not None
    assert detail["resource"]["description"] == "Weathered LD converter slag"
    assert detail["economic"]["net_value"] is not None


def test_duplicate_request_is_rejected(client, kb):
    abc, xyz, match_id = matched(client, kb)
    abc.post(f"/matches/{match_id}/connection-request", json={})
    again = xyz.post("/connections", json={"match_id": match_id})
    assert again.status_code == 409


def test_reject_and_withdraw_transitions(client, kb):
    abc, xyz, match_id = matched(client, kb)
    connection = abc.post(f"/matches/{match_id}/connection-request", json={}).json()
    withdrawn = abc.post(f"/connections/{connection['id']}/withdraw").json()
    assert withdrawn["status"] == "REVOKED"
    assert abc.get(f"/matches/{match_id}").json()["status"] == "INTERESTED"
    second = xyz.post(f"/matches/{match_id}/connection-request", json={}).json()
    rejected = abc.post(f"/connections/{second['id']}/reject", json={"note": "Capacity committed"}).json()
    assert rejected["status"] == "REJECTED"
    assert abc.get(f"/matches/{match_id}").json()["status"] == "REJECTED"


def test_viewer_cannot_manage_connections(client, kb):
    abc, xyz, match_id = matched(client, kb)
    viewer_auth = register_user(client, "viewer@xyz.example")
    xyz.post(f"/organizations/{xyz.org_id}/members", json={"email": "viewer@xyz.example", "role": "VIEWER"})
    viewer = Api(client, viewer_auth["access_token"])
    response = viewer.post(f"/matches/{match_id}/connection-request", json={})
    assert response.status_code == 403 and response.json()["error"]["code"] == "INSUFFICIENT_ROLE"


def test_cannot_connect_on_someone_elses_match(client, kb):
    _abc, _xyz, match_id = matched(client, kb)
    outsider = make_org(client, "Nosy Corp")
    assert outsider.post(f"/matches/{match_id}/connection-request", json={}).status_code == 404


# --- Messaging --------------------------------------------------------------------------------

def test_both_parties_can_message_and_read_receipts_work(client, kb):
    abc, xyz, _match_id, connection = connected(client, kb)
    cid = connection["conversation_id"]
    sent = xyz.post(f"/conversations/{cid}/messages", json={"text": "Can you share the XRF report?"}).json()
    assert sent["is_mine"] is True and sent["read_by_counterpart"] is False
    conversations = abc.get("/conversations").json()
    assert conversations[0]["unread_count"] == 2  # system message + xyz's message
    abc.post(f"/conversations/{cid}/read")
    assert abc.get("/conversations").json()[0]["unread_count"] == 0
    assert xyz.get(f"/conversations/{cid}/messages").json()[-1]["read_by_counterpart"] is True
    reply = abc.post(f"/conversations/{cid}/messages", json={"text": "Uploading it now."})
    assert reply.status_code == 201
    history = xyz.get(f"/conversations/{cid}/messages").json()
    assert [m["body"] for m in history[-2:]] == ["Can you share the XRF report?", "Uploading it now."]
    assert xyz.get(f"/matches/{connection['match_id']}").json()["status"] == "NEGOTIATING"


def test_message_send_is_idempotent_with_client_id(client, kb):
    abc, _xyz, _m, connection = connected(client, kb)
    cid = connection["conversation_id"]
    first = abc.post(f"/conversations/{cid}/messages", json={"text": "Hello", "client_id": "c-1"}).json()
    retry = abc.post(f"/conversations/{cid}/messages", json={"text": "Hello", "client_id": "c-1"}).json()
    assert first["id"] == retry["id"]
    assert len(abc.get(f"/conversations/{cid}/messages").json()) == 2  # system + one


def test_outsider_cannot_read_conversation_by_guessing_id(client, kb):
    _abc, _xyz, _m, connection = connected(client, kb)
    outsider = make_org(client, "Nosy Corp")
    cid = connection["conversation_id"]
    assert outsider.get(f"/conversations/{cid}/messages").status_code == 404
    assert outsider.post(f"/conversations/{cid}/messages", json={"text": "hi"}).status_code == 404


def test_viewer_can_read_but_not_send(client, kb):
    _abc, xyz, _m, connection = connected(client, kb)
    viewer_auth = register_user(client, "viewer2@xyz.example")
    xyz.post(f"/organizations/{xyz.org_id}/members", json={"email": "viewer2@xyz.example", "role": "VIEWER"})
    viewer = Api(client, viewer_auth["access_token"])
    cid = connection["conversation_id"]
    assert viewer.get(f"/conversations/{cid}/messages").status_code == 200
    assert viewer.post(f"/conversations/{cid}/messages", json={"text": "hi"}).status_code == 403


def test_revoked_connection_makes_conversation_read_only(client, kb):
    abc, xyz, match_id, connection = connected(client, kb)
    revoked = abc.post(f"/connections/{connection['id']}/revoke", json={"note": "Project cancelled"}).json()
    assert revoked["status"] == "REVOKED"
    cid = connection["conversation_id"]
    blocked = xyz.post(f"/conversations/{cid}/messages", json={"text": "wait"})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "CONVERSATION_CLOSED"
    assert len(xyz.get(f"/conversations/{cid}/messages").json()) >= 2  # history kept
    assert abc.get(f"/matches/{match_id}").json()["status"] == "CANCELLED"


def test_notifications_follow_the_flow(client, kb):
    abc, xyz, _m, connection = connected(client, kb)
    xyz.post(f"/conversations/{connection['conversation_id']}/messages", json={"text": "Price per tonne?"})
    abc_types = [n["type"] for n in abc.get("/notifications").json()]
    xyz_types = [n["type"] for n in xyz.get("/notifications").json()]
    assert "NEW_MATCH" in abc_types and "NEW_MATCH" in xyz_types
    assert "CONNECTION_REQUEST" in xyz_types
    assert "CONNECTION_ACCEPTED" in abc_types
    assert "NEW_MESSAGE" in abc_types
    message_note = next(n for n in abc.get("/notifications").json() if n["type"] == "NEW_MESSAGE")
    assert "Price per tonne" not in message_note["body"]  # never leak message content
    assert abc.get("/notifications/unread-count").json()["unread"] >= 3
    abc.post("/notifications/read-all")
    assert abc.get("/notifications/unread-count").json()["unread"] == 0


# --- WebSocket --------------------------------------------------------------------------------

def test_websocket_realtime_delivery_and_persistence(client, kb):
    abc, xyz, _m, connection = connected(client, kb)
    cid = connection["conversation_id"]
    with client.websocket_connect(f"/api/v1/ws/conversations/{cid}?token={abc.token}") as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        xyz.post(f"/conversations/{cid}/messages", json={"text": "Live hello"})
        pushed = ws.receive_json()
        assert pushed["type"] == "message" and pushed["message"]["body"] == "Live hello"
        ws.send_json({"type": "message", "text": "Sent over socket", "client_id": "ws-1"})
        frames = [ws.receive_json(), ws.receive_json()]
        assert {f["type"] for f in frames} == {"message", "ack"}
    history = xyz.get(f"/conversations/{cid}/messages").json()
    assert history[-1]["body"] == "Sent over socket"  # persisted, not just broadcast


def test_websocket_rejects_outsiders_and_bad_tokens(client, kb):
    _abc, _xyz, _m, connection = connected(client, kb)
    outsider = make_org(client, "Nosy Corp")
    cid = connection["conversation_id"]
    for token in (outsider.token, "not-a-token"):
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(f"/api/v1/ws/conversations/{cid}?token={token}") as ws:
                ws.receive_json()
        assert exc.value.code == 4403


# --- Documents --------------------------------------------------------------------------------

def test_document_upload_in_conversation_is_shared_with_counterpart_only(client, kb):
    abc, xyz, _m, connection = connected(client, kb)
    cid = connection["conversation_id"]
    upload = abc.post("/documents", files={"file": ("../../etc/XRF report?.pdf", PDF, "application/pdf")},
                      data={"conversation_id": cid})
    assert upload.status_code == 201, upload.text
    doc = upload.json()
    assert doc["file_type"] == "application/pdf"
    assert doc["file_name"] == "XRF report.pdf"  # path stripped, unsafe characters removed
    assert xyz.get(f"/conversations/{cid}/messages").json()[-1]["message_type"] == "DOCUMENT"
    download = xyz.get(f"/documents/{doc['id']}/download")
    assert download.status_code == 200 and download.content == PDF
    assert download.headers["x-content-type-options"] == "nosniff"
    outsider = make_org(client, "Nosy Corp")
    assert outsider.get(f"/documents/{doc['id']}").status_code == 404
    assert outsider.get(f"/documents/{doc['id']}/download").status_code == 404


def test_document_type_is_detected_from_content_not_name(client, kb):
    abc, _xyz, _m, connection = connected(client, kb)
    cid = connection["conversation_id"]
    fake = abc.post("/documents", files={"file": ("spec.pdf", b"MZ\x90\x00\x03\x00\x00\x00\x04\x00", "application/pdf")},
                    data={"conversation_id": cid})
    assert fake.status_code == 422 and fake.json()["error"]["code"] == "FILE_TYPE_NOT_ALLOWED"
    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    infected = abc.post("/documents", files={"file": ("notes.txt", eicar, "text/plain")}, data={"conversation_id": cid})
    assert infected.status_code == 422 and infected.json()["error"]["code"] == "FILE_INFECTED"


def test_document_size_limit(client, kb, monkeypatch):
    from app.core.config import get_settings

    abc, _xyz, _m, connection = connected(client, kb)
    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    too_big = abc.post("/documents", files={"file": ("a.pdf", PDF, "application/pdf")},
                       data={"conversation_id": connection["conversation_id"]})
    assert too_big.status_code == 413 and too_big.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_listing_documents_shared_only_after_connection(client, kb):
    abc, xyz = provider_and_demander(client)
    resource = create_slag(abc, kb)
    create_need(xyz, kb)
    doc = abc.post("/documents", files={"file": ("spec.pdf", PDF, "application/pdf")},
                   data={"resource_id": resource["id"]}).json()
    assert xyz.get(f"/documents/{doc['id']}").status_code == 404  # not before connection
    match_id = abc.get("/matches").json()[0]["id"]
    connection = abc.post(f"/matches/{match_id}/connection-request", json={}).json()
    xyz.post(f"/connections/{connection['id']}/accept")
    assert xyz.get(f"/documents/{doc['id']}").status_code == 200


# --- Exchanges --------------------------------------------------------------------------------

EXCHANGE = {"agreed_quantity": 1500, "unit": "tonne", "agreed_frequency": "MONTH", "agreed_price_per_unit": 250,
            "start_date": "2026-11-01", "end_date": "2027-06-30", "delivery_terms": {"transport": "Road"}}


def test_exchange_requires_accepted_connection(client, kb):
    abc, _xyz, match_id = matched(client, kb)
    response = abc.post(f"/matches/{match_id}/exchange", json=EXCHANGE)
    assert response.status_code == 409 and response.json()["error"]["code"] == "CONNECTION_REQUIRED"


def test_exchange_lifecycle_drives_match_status(client, kb):
    abc, xyz, match_id, connection = connected(client, kb)
    created = abc.post(f"/matches/{match_id}/exchange", json=EXCHANGE)
    assert created.status_code == 201, created.text
    exchange = created.json()
    assert exchange["status"] == "PLANNED"
    assert abc.get(f"/matches/{match_id}").json()["status"] == "NEGOTIATING"
    assert abc.post(f"/matches/{match_id}/exchange", json=EXCHANGE).status_code == 409  # one open exchange

    started = xyz.post(f"/exchanges/{exchange['id']}/start").json()
    assert started["status"] == "IN_PROGRESS" and started["started_at"]
    assert abc.get(f"/matches/{match_id}").json()["status"] == "ACTIVE_EXCHANGE"
    # Terms are locked while in progress; the connection cannot be revoked mid-exchange.
    assert abc.patch(f"/exchanges/{exchange['id']}", json={"agreed_quantity": 10}).status_code == 409
    assert abc.post(f"/connections/{connection['id']}/revoke", json={}).status_code == 409

    completed = abc.post(f"/exchanges/{exchange['id']}/complete", json={"delivered_quantity": 9000}).json()
    assert completed["status"] == "COMPLETED" and float(completed["delivered_quantity"]) == 9000
    assert abc.get(f"/matches/{match_id}").json()["status"] == "COMPLETED"
    updates = [m for m in abc.get(f"/conversations/{connection['conversation_id']}/messages").json()
               if m["message_type"] == "STRUCTURED_UPDATE"]
    assert len(updates) == 3  # proposed, in progress, completed


def test_cancelled_exchange_returns_match_to_negotiation(client, kb):
    abc, xyz, match_id, _c = connected(client, kb)
    exchange = abc.post(f"/matches/{match_id}/exchange", json=EXCHANGE).json()
    xyz.post(f"/exchanges/{exchange['id']}/start")
    cancelled = xyz.post(f"/exchanges/{exchange['id']}/cancel", json={"reason": "Quality dispute"}).json()
    assert cancelled["status"] == "CANCELLED"
    assert abc.get(f"/matches/{match_id}").json()["status"] == "NEGOTIATING"
    invalid = xyz.post(f"/exchanges/{exchange['id']}/start")
    assert invalid.status_code == 409 and invalid.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
