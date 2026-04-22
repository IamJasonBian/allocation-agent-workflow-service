from allocation_agent.config import settings
from allocation_agent.stores.feedback import recent_outcomes
from allocation_agent.tasks.select import tick


def test_tick_eager_chain(memory_db, celery_eager, monkeypatch):
    monkeypatch.setattr(settings, "apply_mode", "mock")
    n = tick("candidate-eager", queue_size=2)
    assert n == 2
    assert len(recent_outcomes(10)) == 2
