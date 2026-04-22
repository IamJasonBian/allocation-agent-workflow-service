# allocation-agent-workflow-service — architecture & decisions

> Snapshot of what this service is, how it fits with the rest of the stack,
> and the open design choices. Rev this file as decisions land.

## The three services

```
┌─────────┐                         ┌─────────┐                          ┌──────────────┐
│ finders │── raw URL / hint ──────▶│ crawler │── canonical JobCand ────▶│ orchestrator │
│         │   POST /enqueue_url     │         │   (GET /api/jobs via     │ (this repo)  │
│ vc-feed │                         │         │    CrawlerSource)        │              │
│ gmail   │                         │         │                          │              │
│ manual  │                         │         │                          │              │
└─────────┘                         └─────────┘                          └──────────────┘
                                                                                 ▲
    ┌────── manual / referral / side-channel ───── POST /v1/ingest/candidates ───┘
    │                                              (escape hatch — see below)
    │
    └────── gmail poller / browser ext ─────────── POST /v1/ingest/callback
                                                   POST /v1/ingest/outcome
```

### Role of each service

| Service | Owns | Does not own |
|---|---|---|
| **Finder** (discovery) | "there might be a job here" — a URL, a referral, a hint | normalization, dedup, rate-limit politeness |
| **Crawler** (`services/allocation-crawler-service` in v1) | canonical `JobCandidate` shape, ATS fingerprinting, dedup, freshness, robots.txt, per-host rate limits | ranking, applying, callbacks |
| **Orchestrator** (this repo) | ranking, cooldowns, selector policy, apply pipeline, feedback loop | crawl politeness, ATS normalization |

### The canonical `JobCandidate` lives in exactly one place: the crawler's output.

## Inbound paths to the orchestrator

### Primary: `CrawlerSource` (pull)

Each selector tick pulls the latest jobs from the crawler via a new source in our registry:

```python
# sources/crawler.py — registered as "crawler" in _REGISTRY
class CrawlerSource:
    name = "crawler"
    def iter_candidates(self) -> Iterable[JobCandidate]:
        # GET {CRAWLER_BASE_URL}/api/jobs?since=<hwm>&limit=1000
        ...
```

**Why pull instead of push**:
- Selector tick already exists — it's the natural pull moment
- Crawler doesn't need to know about orchestrators (multi-candidate friendly)
- Crawler down → orchestrator degrades gracefully to last-known inventory
- Back-pressure is implicit: orchestrator pulls when it can handle more

### Secondary: `/v1/ingest/candidates` (push, escape hatch)

Narrow set of legitimate callers:
1. Urgent manual picks ("apply to this today, don't wait for crawler")
2. Pre-enriched external data (headhunter batches)
3. Testing / bootstrap before crawler exists

**Not for**: raw-URL finders. Those feed the crawler, not us.

### Feedback inbound: `/v1/ingest/outcome` and `/v1/ingest/callback`

- Outcome ingest: retroactive logging from alternative apply paths (v1 Puppeteer, manual applies)
- Callback ingest: recruiter responses from Gmail poller, LinkedIn scraper, Chrome extension

See `docs/ingest-api.md` (TODO) for full endpoint schemas.

## Source registry

Added in PR #1 (refactor/load-candidates):

- `sources/base.py` — `JobSource` Protocol (`name`, `iter_candidates() -> Iterable[JobCandidate]`)
- `sources/__init__.py` — `load_candidates()` merges, dedupes on `(company_id, job_id)`, sorts by `expected_callback_prob`
- `sources/dover.py` — `DoverSource` (mock fixture or real v1 Dover feed)
- `sources/crawler.py` — `CrawlerSource` (**currently mocked**; real HTTP client is follow-up)

Sources enabled via `settings.enabled_sources: list[str]` (default `["dover"]`).

## Celery queue topology

Three queues on Redis, one broker:

| Queue | Producer | Consumer | Purpose |
|---|---|---|---|
| `select` | CLI (`select-tick`) or beat | `tasks/select.py:tick` | Plan the next N jobs |
| `apply` | `select` task | `tasks/apply.py:apply_to_job` | Run the apply (mock or Node/Puppeteer) |
| `feedback` | `apply` task, future `/ingest/*` | `tasks/feedback.py:record_outcome_task`, `record_callback_task` | Persist to SQLite |

## Apply modes

- `APPLY_MODE=mock` (default) — deterministic hash-based outcomes, no browser
- `APPLY_MODE=node` — subprocesses `node_agent/apply.mjs` with puppeteer-core

## Isolation modes

- `ISOLATION_MODE=none` (default)
- `ISOLATION_MODE=mac_os_space` — Node agent installs focus-loss watcher, aborts with `status=interrupted` if the tab stays hidden beyond `ISOLATION_FOCUS_LOSS_GRACE_S` (default 3s). Guardrail for running on a dedicated macOS Space.

## OutcomeStatus

```python
Literal["submitted", "blocked", "captcha", "error", "skipped", "needs_auth", "interrupted"]
```

## Key decisions log

| Decision | Why |
|---|---|
| Celery (not Temporal) for Phase 1 | Known primitives, fastest to ship. Migrate if delayed-callback workflow complexity justifies it. |
| Node subprocess (not Playwright-Python) for apply | Reuse v1's browser knowledge and stealth patterns. Rewrite to Playwright-Python if Node bridge becomes painful. |
| SQLite (not Postgres) for feedback store | Single-candidate scale. Swap when multi-candidate lands. |
| Mock mode as default (not node) | Tests run without browser; new contributors can iterate without Chrome. |
| `/v1/` URL versioning on ingest API | Cheap insurance. Callers drift on their own clocks. |
| Crawler owns `JobCandidate` canonicalization | Single source of truth. Finders stay dumb. Orchestrator stays focused. |
| Pull from crawler, not push | Selector tick is the natural pull moment. Decouples crawler from orchestrator count. |
| Source dedupe key = `(company_id, job_id)` | Same job on two feeds (Dover + direct Greenhouse) collapses to one. |

## Open questions

- Do we stand up a separate `docs/ingest-api.md` with full Pydantic request/response schemas before implementing, or implement + generate OpenAPI?
- Crawler high-water mark — client-side cursor file vs server-side `since=` param? Default to server-managed.
- Idempotency key strategy for `/ingest/*` — per-record natural key vs caller-supplied header? Both, with header precedence.
- Multi-candidate: when do we split candidate profiles out of `~/.config/allocation-agent/candidate.json` into a candidate table?

## Phase status

- **Phase 1 (done)**: Celery plumbing, mock apply, Dover fixture source, SQLite feedback, FastAPI dashboard (read-only), isolation mode v1, refactor to source registry.
- **Phase 2 (next)**: `CrawlerSource` real HTTP client, `/v1/ingest/*` endpoints with Pydantic request models + dedupe.
- **Phase 3**: Gmail callback poller, OAuth token store, LLM ranker, DeepFM alternate ranker, per-ATS rate limits, cooldown store.

## Related architecture writeups

- `chasethedice` blog posts (latest commit on `main`):
  - `next-best-job-production-arch` — selector/ranker/queue design
  - `job-discovery-and-crawl-quality` — crawler side, robots.txt, politeness
  - `breaking-down-rag-for-agents` — RAG for the LLM ranker
