# allocation-agent

Local Celery-based job-application agent pipeline.

This is the runtime skeleton for the architecture documented at:

- [Next-Best-Job Production Architecture](http://localhost:1313/chasethedice/posts/next-best-job-production-arch/) — the selector / ranker / queue design
- [Job Discovery and Crawl Quality](http://localhost:1313/chasethedice/posts/job-discovery-and-crawl-quality/) — the upstream job index this pipeline consumes
- [Breaking Down a RAG System for Agent-Based Applications](http://localhost:1313/chasethedice/posts/breaking-down-rag-for-agents/) — retrieval for the LLM ranker and the agent context pack

## Scope of this skeleton

Phase 1 (this commit): worker plumbing only.

- Redis broker via `docker compose`
- Celery app with three queues: `select`, `apply`, `feedback`
- `select` task: stub selector that emits `(candidate_id, job_id)` pairs onto the `apply` queue
- `apply` task: stub agent that logs, waits, writes an outcome to the `feedback` queue
- `feedback` task: persists outcomes to a local SQLite store
- CLI to seed, enqueue, and inspect

Phase 2 (next): real ranker integration (LLM + DeepFM), job index hookup, per-ATS rate limits.

Phase 3: browser agent (Playwright + Claude API), captcha detection, callback ingestion.

## Layout

```
allocation-agent/
├── docker-compose.yml        # redis broker
├── pyproject.toml
├── .env.example
├── src/allocation_agent/
│   ├── celery_app.py         # Celery instance + queue topology
│   ├── config.py             # env-driven settings
│   ├── schemas.py            # JobCandidate, AgentDispatch, ApplyOutcome
│   ├── cli.py                # click CLI: seed, enqueue, tail
│   ├── tasks/
│   │   ├── select.py         # selector task (stub)
│   │   ├── apply.py          # apply task (stub)
│   │   └── feedback.py       # outcome persistence
│   └── stores/
│       └── feedback.py       # SQLite feedback store
└── scripts/
    ├── run_worker.sh
    └── run_beat.sh
```

## Quickstart

Requires Python 3.11+, Docker, `uv` (or pip).

```bash
cd /Users/jasonzb/Desktop/apollo/gamma/allocation-agent

# 1. Start Redis
docker compose up -d

# 2. Install deps
uv sync   # or: pip install -e .

# 3. Start a worker (in one terminal)
./scripts/run_worker.sh

# 4. Enqueue a selector tick (in another)
uv run allocation-agent select-tick --candidate-id demo-candidate

# 5. Tail the feedback store
uv run allocation-agent tail
```

## Queue topology

| Queue | Producer | Consumer | Purpose |
|---|---|---|---|
| `select` | CLI / beat | selector worker | Decide next-N jobs for a candidate |
| `apply` | selector | apply worker | Run the agent against a single job |
| `feedback` | apply worker | feedback worker | Persist outcome + delayed callback signals |

Worker concurrency is per-queue. The `apply` queue is where per-ATS rate limiting lives (see `tasks/apply.py`).
