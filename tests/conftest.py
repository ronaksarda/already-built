import pytest

from core import pipeline


@pytest.fixture(autouse=True)
def _fresh_gemma_health():
    # The planner's failure breaker is process-wide; each test starts with a healthy Gemma.
    pipeline._gemma_health.update(fails=0, since=0.0)
    yield
