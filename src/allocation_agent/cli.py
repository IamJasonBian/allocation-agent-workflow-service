import json

import click

from .config import settings
from .integrations.allocation_crawler import (
    greenhouse_board_frontier_url,
    list_boards,
)
from .stores.feedback import (
    list_applications,
    pick_work,
    recent_outcomes,
    seed_mock_applications,
)
from .simulation import run_simulation
from .tasks.select import tick


@click.group()
def cli() -> None:
    """allocation-agent control surface."""


@cli.group("finder")
def finder_group() -> None:
    """Talk to finder-mock (`CRAWLER_BASE_URL` / settings.crawler_base_url)."""


@finder_group.command("seed")
@click.argument("url")
@click.option("--depth", default=0, show_default=True)
def finder_seed_cmd(url: str, depth: int) -> None:
    """POST /v1/seed — enqueue a URL (requires finder-mock running)."""
    from .integrations.finder import seed_finder_url

    click.echo(json.dumps(seed_finder_url(url, depth=depth), indent=2))


@finder_group.command("batch")
@click.argument("urls", nargs=-1, required=True)
@click.option("--depth", default=0, show_default=True)
def finder_batch_cmd(urls: tuple[str, ...], depth: int) -> None:
    """POST /v1/seed/batch with one or more URL arguments."""
    from .integrations.finder import seed_finder_batch

    click.echo(json.dumps(seed_finder_batch(list(urls), depth=depth), indent=2))


@finder_group.command("status")
def finder_status_cmd() -> None:
    """GET /v1/status from the finder-mock process."""
    from .integrations.finder import finder_status

    click.echo(json.dumps(finder_status(), indent=2))


@finder_group.command("ping")
def finder_ping_cmd() -> None:
    """Return exit 0 if GET /health on ``CRAWLER_BASE_URL`` succeeds (finder-mock up)."""
    from .integrations.finder import finder_reachable

    if finder_reachable():
        click.echo("ok")
        return
    raise click.ClickException("finder not reachable (start finder-mock on crawler_base_url)")


_DEFAULT_ALLOC_API = "https://allocation-crawler-service.netlify.app/api/crawler"


@cli.group("crawler")
def crawler_group() -> None:
    """Query the public Allocation Crawler API (board list, Greenhouse frontiers)."""


@crawler_group.command("boards")
@click.option(
    "--api-url",
    default=_DEFAULT_ALLOC_API,
    show_default=True,
    help="Crawler API root (Allocation Crawler Service).",
)
@click.option(
    "--ats",
    "ats_filter",
    default=None,
    type=str,
    help="Only print boards for this ATS (e.g. greenhouse).",
)
def crawler_boards_cmd(api_url: str, ats_filter: str | None) -> None:
    """List registered boards. For each Greenhouse board, show a standard ``job-boards`` frontier URL."""
    base = api_url.rstrip("/")
    data = list_boards(base)
    boards = data.get("boards") or []
    if ats_filter:
        t = ats_filter.strip().lower()
        boards = [b for b in boards if (b or {}).get("ats", "").lower() == t]
    # Keep output stable and small for a quick look.
    for b in sorted(boards, key=lambda x: (x or {}).get("company") or ""):
        bid = b.get("id", "")
        co = b.get("company", "")
        ats = b.get("ats", "")
        line = f"{ats}\t{co}\t{bid}"
        if (ats or "").lower() == "greenhouse" and bid:
            line += f"\t{greenhouse_board_frontier_url(bid)}"
        click.echo(line)


@cli.command("select-tick")
@click.option("--candidate-id", required=True)
@click.option("--queue-size", default=5, show_default=True)
@click.option(
    "--random",
    "random_sample",
    is_flag=True,
    help="Testing: random sample of the eligible pool instead of ranked top-N.",
)
@click.option(
    "--seed",
    type=int,
    default=None,
    help="Seed --random for reproducibility; leave unset for a fresh sample each run.",
)
def select_tick(
    candidate_id: str,
    queue_size: int,
    random_sample: bool,
    seed: int | None,
) -> None:
    """Enqueue a selector tick for a candidate."""
    res = tick.apply_async(
        args=[candidate_id, queue_size],
        kwargs={"random_sample": random_sample, "seed": seed},
        queue="select",
    )
    mode = "random-sample" if random_sample else "ranked"
    click.echo(f"queued select tick ({mode}): {res.id}")


@cli.command("simulate")
@click.option("--candidate-id", default="sim-nyc", show_default=True)
@click.option("--queue-size", default=5, show_default=True)
@click.option("--no-persist", is_flag=True, help="Do not write to the feedback DB.")
def simulate_cmd(candidate_id: str, queue_size: int, no_persist: bool) -> None:
    """Run selector + apply in-process (uses APPLY_MODE, no Celery)."""
    result = run_simulation(candidate_id, queue_size, persist=not no_persist)
    click.echo(json.dumps(result, indent=2))


@cli.command("dry-run")
@click.option("--candidate-id", default="dry-run", show_default=True)
@click.option(
    "--queue-size",
    default=2,
    show_default=True,
    help="Top-N jobs from merged enabled sources (default 2).",
)
@click.option(
    "--persist",
    is_flag=True,
    help="Write mock apply outcomes to the feedback DB (default: off, unlike ``simulate``).",
)
def dry_run_cmd(candidate_id: str, queue_size: int, persist: bool) -> None:
    """Safe pipeline run: requires ``APPLY_MODE=mock`` (no Puppeteer). Uses ``load_candidates()`` and your ``ENABLED_SOURCES``.

    For finder-mock: default ``FINDER_WORKERS=2``. Seeds require a conservative
    ``robots.txt`` verdict (or 404 = no file). For local-only tests:
    ``FINDER_ROBOTS_LOCAL_BYPASS=1``; never disable enforcement on public URLs.
    """
    if settings.apply_mode != "mock":
        raise click.ClickException(
            "dry-run only runs with APPLY_MODE=mock (no Puppeteer / Chrome). "
            f"Current APPLY_MODE is {settings.apply_mode!r}."
        )
    result = run_simulation(candidate_id, queue_size, persist=persist)
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


@cli.command("seed-applications")
@click.option("--candidate-id", default="jason", show_default=True)
def seed_applications_cmd(candidate_id: str) -> None:
    """Populate the local ledger with mock application rows in each state."""
    inserted = seed_mock_applications(candidate_id)
    click.echo(f"seeded {inserted} mock applications for {candidate_id}")


@cli.command("applications")
@click.option("--candidate-id", default=None)
def applications_cmd(candidate_id: str | None) -> None:
    """List applications ledger rows (one JSON object per line)."""
    for row in list_applications(candidate_id):
        click.echo(json.dumps(row))


@cli.command("pick")
@click.option("--candidate-id", default="jason", show_default=True)
@click.option("--limit", default=3, show_default=True)
@click.option("--lease-seconds", default=900, show_default=True)
def pick_cmd(candidate_id: str, limit: int, lease_seconds: int) -> None:
    """Atomically dispatch top-N eligible rows (moves them to in_flight)."""
    picked = pick_work(candidate_id, limit, lease_seconds)
    for c, j in picked:
        click.echo(json.dumps({"candidate_id": c, "job_id": j}))
