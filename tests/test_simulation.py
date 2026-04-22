from allocation_agent.simulation import run_simulation


def test_simulation_persist(memory_db):
    r = run_simulation("sim-user", queue_size=3, persist=True)
    assert r["jobs_considered"] == 3
    assert len(r["outcomes"]) == 3


def test_simulation_no_persist(memory_db):
    from allocation_agent.stores.feedback import recent_outcomes

    r = run_simulation("sim-user", queue_size=2, persist=False)
    assert len(r["outcomes"]) == 2
    assert len(recent_outcomes(10)) == 0

