import pytest

from allocation_agent.config import settings
from allocation_agent.stores import feedback as fb


@pytest.fixture
def memory_db(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "feedback_db_url", "sqlite:///:memory:")
    monkeypatch.setattr(settings, "apply_mode", "mock")
    fb.reset_feedback_store()
    yield
    fb.reset_feedback_store()


@pytest.fixture
def celery_eager():
    from allocation_agent.celery_app import app

    prev_eager = app.conf.task_always_eager
    prev_prop = app.conf.task_eager_propagates
    app.conf.task_always_eager = True
    app.conf.task_eager_propagates = True
    yield app
    app.conf.task_always_eager = prev_eager
    app.conf.task_eager_propagates = prev_prop
