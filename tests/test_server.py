"""HTTP-level edge cases. No real API calls: keys are removed and the pipeline is stubbed."""
import time

import pytest
from fastapi.testclient import TestClient

import server
from core import gemma, groq


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(gemma, "api_key", lambda: "")
    monkeypatch.setattr(groq, "api_key", lambda: "")
    monkeypatch.setattr(server, "_warm", lambda: server.embed_state.update(ready=True))
    server._hits.clear()
    server.jobs.clear()
    with TestClient(server.app) as c:
        yield c


def _wait(c, job_id):
    for _ in range(50):
        r = c.get(f"/api/check/{job_id}").json()
        if r["state"] == "done":
            return r["result"]
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_index_and_health(client):
    assert "ALREADY BUILT?" in client.get("/").text
    h = client.get("/api/health").json()
    assert h["gemma"] is False and h["groq"] is False


def test_empty_idea_never_calls_apis(client, monkeypatch):
    monkeypatch.setattr(server.pipeline.gemma, "plan", lambda *a, **k: pytest.fail("Gemma must not be called"))
    job = client.post("/api/check", data={"idea": "  "}).json()["job_id"]
    assert _wait(client, job)["status"] == "empty"


def test_pipeline_crash_returns_message(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(server.pipeline, "run", boom)
    job = client.post("/api/check", data={"idea": "An app that turns lecture slides into flashcards"}).json()["job_id"]
    assert _wait(client, job)["status"] == "crashed"


def test_unknown_job(client):
    assert client.get("/api/check/nope").status_code == 404


def test_rate_limit(client, monkeypatch):
    monkeypatch.setitem(server.LIMITS, "check", (2, 600))
    monkeypatch.setattr(server.pipeline, "run", lambda *a, **k: {"status": "ok"})
    codes = [client.post("/api/check", data={"idea": f"An app that turns lecture slides into flashcards, version {i}"}).status_code for i in range(3)]
    assert codes == [200, 200, 429]


def test_same_idea_is_served_from_cache(client, monkeypatch):
    calls = []
    monkeypatch.setattr(server.pipeline, "run", lambda *a, **k: calls.append(1) or {"status": "ok", "errors": []})
    a = client.post("/api/check", data={"idea": "Same  Idea: lecture slides into FLASHCARDS for nurses"}).json()
    _wait(client, a["job_id"])
    b = client.post("/api/check", data={"idea": "same idea: lecture slides into flashcards for nurses"}).json()
    assert b.get("cached") and len(calls) == 1
    c = client.post("/api/check", data={"idea": "same idea: lecture slides into flashcards for nurses", "force": "true"}).json()
    _wait(client, c["job_id"])
    assert not c.get("cached") and len(calls) == 2


def test_chat_needs_a_result_and_a_key(client):
    r = client.post("/api/chat", json={"job_id": "", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 400
    r = client.post("/api/chat", json={"job_id": "", "messages": [{"role": "user", "content": "hi"}], "result": {"status": "ok", "idea": "x", "top": []}})
    assert r.status_code == 503 and "GROQ_API_KEY" in r.json()["detail"]
    r = client.post("/api/chat", json={"job_id": "", "messages": [{"role": "assistant", "content": "hi"}]})
    assert r.status_code == 400


def test_chat_message_too_long(client):
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": "x" * 5000}]})
    assert r.status_code == 422


def test_transcribe_without_key_tells_page_to_fall_back(client):
    r = client.post("/api/transcribe", files={"audio": ("a.webm", b"x" * 5000, "audio/webm")})
    assert r.status_code == 503 and r.json()["detail"] == "no_server_stt"


def test_transcribe_too_short(client, monkeypatch):
    monkeypatch.setattr(groq, "api_key", lambda: "k")
    r = client.post("/api/transcribe", files={"audio": ("a.webm", b"x" * 100, "audio/webm")})
    assert r.status_code == 400


def test_demo(client):
    r = client.get("/api/demo")
    assert r.status_code == 200 and r.json()["demo"] is True


def test_rejected_input_does_not_use_the_rate_limit(client, monkeypatch):
    monkeypatch.setitem(server.LIMITS, "check", (1, 600))
    for bad in ["", "hi", "nice nice nice very nice"]:
        r = client.post("/api/check", data={"idea": bad})
        assert r.status_code == 200
        assert _wait(client, r.json()["job_id"])["status"] in ("empty", "short", "vague")
    monkeypatch.setattr(server.pipeline, "run", lambda *a, **k: {"status": "ok", "errors": []})
    assert client.post("/api/check", data={"idea": "An app that turns lecture slides into flashcards"}).status_code == 200


def test_huge_idea_field_is_capped(client):
    r = client.post("/api/check", data={"idea": "word " * 50_000})
    assert _wait(client, r.json()["job_id"])["status"] == "long"


def test_security_headers(client):
    h = client.get("/").headers
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["x-content-type-options"] == "nosniff"
    assert client.get("/api/health").headers["cache-control"] == "no-store"


def test_chat_with_malformed_result_is_a_clean_error(client, monkeypatch):
    monkeypatch.setattr(groq, "api_key", lambda: "k")
    bad = {"status": "ok", "idea": "x", "top": [{"id": "a", "name": "b", "score": "NaN-text", "stars": "x"}]}
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}], "result": bad})
    assert r.status_code in (400, 503)
