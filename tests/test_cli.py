from click.testing import CliRunner

from allocation_agent.cli import cli


def test_cli_simulate_no_persist(monkeypatch):
    monkeypatch.setenv("FEEDBACK_DB_URL", "sqlite:///:memory:")
    from allocation_agent.config import settings
    from allocation_agent.stores import feedback as fb

    monkeypatch.setattr(settings, "feedback_db_url", "sqlite:///:memory:")
    monkeypatch.setattr(settings, "apply_mode", "mock")
    fb.reset_feedback_store()

    runner = CliRunner()
    r = runner.invoke(cli, ["simulate", "--no-persist", "--queue-size", "1"])
    assert r.exit_code == 0
    assert "outcomes" in r.output
