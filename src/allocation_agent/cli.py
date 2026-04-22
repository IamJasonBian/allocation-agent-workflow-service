import json

import click

from .stores.feedback import recent_outcomes
from .simulation import run_simulation
from .tasks.select import tick


@click.group()
def cli() -> None:
    """allocation-agent control surface."""


@cli.command("select-tick")
@click.option("--candidate-id", required=True)
@click.option("--queue-size", default=5, show_default=True)
def select_tick(candidate_id: str, queue_size: int) -> None:
    """Enqueue a selector tick for a candidate."""
    res = tick.apply_async(args=[candidate_id, queue_size], queue="select")
    click.echo(f"queued select tick: {res.id}")


@cli.command("simulate")
@click.option("--candidate-id", default="sim-nyc", show_default=True)
@click.option("--queue-size", default=5, show_default=True)
@click.option("--no-persist", is_flag=True, help="Do not write to the feedback DB.")
def simulate_cmd(candidate_id: str, queue_size: int, no_persist: bool) -> None:
    """Run selector + apply in-process (uses APPLY_MODE, no Celery)."""
    result = run_simulation(candidate_id, queue_size, persist=not no_persist)
    click.echo(json.dumps(result, indent=2))


@cli.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8080, show_default=True)
def serve_cmd(host: str, port: int) -> None:
    """Operator dashboard (FastAPI + static HTML)."""
    import uvicorn

    uvicorn.run(
        "allocation_agent.web.dashboard:app",
        host=host,
        port=port,
        reload=False,
    )


@cli.command("tail")
@click.option("--limit", default=20, show_default=True)
def tail(limit: int) -> None:
    """Print recent outcomes from the feedback store."""
    for row in recent_outcomes(limit):
        click.echo(json.dumps(row))
