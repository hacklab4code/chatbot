"""Test dell'API HTTP (senza LLM reale)."""
import pytest
from fastapi.testclient import TestClient

from app import config, main
from app.llm import LLMError


class FakeAgent:
    def __init__(self):
        self.received = []
        self.sessions = type("S", (), {"reset": staticmethod(lambda sid: True)})()

    def handle(self, session_id, message, channel):
        self.received.append(message)
        return {"session_id": session_id, "reply": "ok", "actions": []}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "api.db")
    monkeypatch.setattr(config, "API_KEY", "segreta")
    monkeypatch.setattr(main.llm, "resolve_model", lambda: "fake")
    monkeypatch.setattr(main.llm, "available_models", lambda: ["fake"])
    fake = FakeAgent()
    monkeypatch.setattr(main, "agent", fake)
    with TestClient(main.app) as c:
        c.fake = fake
        yield c


H = {"X-API-Key": "segreta"}
SID = "abcdef0123456789"


def test_api_key_required(client):
    assert client.get("/api/v1/menu").status_code == 401
    assert client.get("/api/v1/menu", headers={"X-API-Key": "sbagliata"}).status_code == 401
    assert client.get("/api/v1/menu", headers=H).status_code == 200
    assert client.get("/health").status_code == 200  # health è pubblico


def test_chat_redacts_raw_personal_data(client):
    r = client.post("/api/v1/chat", headers=H,
                    json={"session_id": SID, "message": "chiamatemi al 333 1234567", "channel": "chat"})
    assert r.status_code == 200 and r.json()["privacy_warnings"] == ["TEL"]
    assert "333" not in client.fake.received[0]


def test_chat_validation(client):
    assert client.post("/api/v1/chat", headers=H, json={"session_id": "x", "message": "ciao"}).status_code == 422
    assert client.post("/api/v1/chat", headers=H,
                       json={"session_id": SID, "message": "ciao", "channel": "fax"}).status_code == 422


def test_llm_down_returns_503(client, monkeypatch):
    def boom(*a):
        raise LLMError("giù")
    monkeypatch.setattr(client.fake, "handle", boom)
    r = client.post("/api/v1/chat", headers=H, json={"session_id": SID, "message": "ciao"})
    assert r.status_code == 503


def test_rest_booking_flow(client):
    r = client.get("/api/v1/availability", headers=H, params={"date": "2026-10-19", "time": "20:00", "party_size": 2})
    assert r.status_code == 422 and "lunedì" in r.json()["detail"]
    bad = {"date": "2099-01-01", "time": "20:00", "party_size": 2, "customer_name": "mario@example.com"}
    assert client.post("/api/v1/reservations", headers=H, json=bad).status_code == 422
