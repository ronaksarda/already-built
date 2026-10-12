import pytest

from core import gemma, pipeline


@pytest.fixture(autouse=True)
def _fresh_gemma_health():
    # The planner's failure breaker is process-wide; each test starts with a healthy Gemma.
    pipeline._gemma_health.update(fails=0, since=0.0)
    yield


@pytest.fixture(autouse=True)
def _no_real_gemma_chat(monkeypatch):
    # The report/chat fallback must never reach the real Gemini API from a test.
    def offline(*a, **k):
        raise gemma.GemmaError("Gemma is offline in tests.")

    monkeypatch.setattr(gemma, "chat", offline)
