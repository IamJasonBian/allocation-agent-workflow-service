from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import JSON, Column, DateTime, Integer, String, and_, create_engine, or_
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import StaticPool

from ..config import settings
from ..schemas import ApplyOutcome, CallbackSignal, JobCandidate


APPLICATION_STATES = ("eligible", "in_flight", "done", "abandoned")

BACKOFF_BY_STATUS: dict[str, timedelta | None] = {
    "captcha":     timedelta(hours=24),
    "blocked":     timedelta(hours=48),
    "interrupted": timedelta(seconds=0),
    # "error" uses exponential backoff, computed from historical error count
}

ABANDON_AFTER_ERRORS = 3
DEFAULT_LEASE_SECONDS = 900   # 15 min


class Base(DeclarativeBase):
    pass


class OutcomeRow(Base):
    __tablename__ = "outcomes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(String, index=True, nullable=False)
    job_id = Column(String, index=True, nullable=False)
    ats = Column(String, nullable=False)
    status = Column(String, nullable=False)
    message = Column(String, default="")
    tokens_spent = Column(Integer, default=0)
    wallclock_ms = Column(Integer, default=0)
    finished_at = Column(DateTime, default=datetime.utcnow)


class CallbackRow(Base):
    __tablename__ = "callbacks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(String, index=True, nullable=False)
    job_id = Column(String, index=True, nullable=False)
    kind = Column(String, nullable=False)
    received_at = Column(DateTime, default=datetime.utcnow)
    raw = Column(JSON, nullable=True)


class ApplicationRow(Base):
    """Ledger of (candidate, job) work units. See docs/architecture.md § Work-queue.

    State machine:
        eligible ─pick+lease─▶ in_flight ─outcome─▶ done | abandoned | eligible (+ wait_until)

    `wait_until` is polymorphic by state:
        eligible:   don't re-pick until this time (backoff). NULL = pickable now.
        in_flight:  lease expiration. Expired lease = implicit eligible.
        done/abandoned: NULL.
    """
    __tablename__ = "applications"
    candidate_id = Column(String, primary_key=True)
    job_id       = Column(String, primary_key=True)
    state        = Column(String, nullable=False, default="eligible")
    wait_until   = Column(DateTime, nullable=True)


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        url = str(settings.feedback_db_url)
        kw: dict = {"future": True}
        if url.startswith("sqlite"):
            kw["connect_args"] = {"check_same_thread": False}
            if ":memory:" in url:
                kw["poolclass"] = StaticPool
        _engine = create_engine(url, **kw)
        Base.metadata.create_all(_engine)
    return _engine


def reset_feedback_store() -> None:
    """Dispose the SQL engine (tests can change `settings.feedback_db_url` then call this)."""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None


def record_outcome(outcome: ApplyOutcome) -> int:
    with Session(get_engine()) as s:
        row = OutcomeRow(**outcome.model_dump())
        s.add(row)
        s.commit()
        return row.id


def record_callback(signal: CallbackSignal) -> int:
    with Session(get_engine()) as s:
        row = CallbackRow(
            candidate_id=signal.candidate_id,
            job_id=signal.job_id,
            kind=signal.kind,
            received_at=signal.received_at,
            raw={"raw": signal.raw} if signal.raw else None,
        )
        s.add(row)
        s.commit()
        return row.id


def ensure_applications(candidate_id: str, jobs: Iterable[JobCandidate]) -> int:
    """INSERT OR IGNORE new (candidate, job) pairs as eligible. Returns new-row count."""
    with Session(get_engine()) as s:
        inserted = 0
        for job in jobs:
            if s.get(ApplicationRow, (candidate_id, job.job_id)) is None:
                s.add(ApplicationRow(
                    candidate_id=candidate_id,
                    job_id=job.job_id,
                    state="eligible",
                    wait_until=None,
                ))
                inserted += 1
        s.commit()
        return inserted


def pick_work(
    candidate_id: str,
    limit: int,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    preferred_job_ids: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Atomically move up to `limit` eligible rows to in_flight with a lease.

    If `preferred_job_ids` is given, pick in that order (caller-ranked).
    Otherwise pick any eligible row (wait_until-ordered, NULL first).
    Reclaims rows with expired in_flight leases (crash recovery) in both modes.

    Returns `[(candidate_id, job_id), ...]` for dispatched items.
    """
    now = datetime.utcnow()
    lease_until = now + timedelta(seconds=lease_seconds)
    picked: list[tuple[str, str]] = []

    eligible_filter = or_(
        and_(
            ApplicationRow.state == "eligible",
            or_(
                ApplicationRow.wait_until.is_(None),
                ApplicationRow.wait_until < now,
            ),
        ),
        and_(
            ApplicationRow.state == "in_flight",
            ApplicationRow.wait_until < now,
        ),
    )

    with Session(get_engine()) as s:
        if preferred_job_ids is not None:
            # Caller ranked — preserve that order; transition each that's pickable.
            by_id = {
                r.job_id: r
                for r in s.query(ApplicationRow)
                .filter(
                    ApplicationRow.candidate_id == candidate_id,
                    ApplicationRow.job_id.in_(preferred_job_ids),
                    eligible_filter,
                )
                .all()
            }
            for jid in preferred_job_ids:
                if len(picked) >= limit:
                    break
                row = by_id.get(jid)
                if row is None:
                    continue
                row.state = "in_flight"
                row.wait_until = lease_until
                picked.append((row.candidate_id, row.job_id))
        else:
            rows = (
                s.query(ApplicationRow)
                .filter(ApplicationRow.candidate_id == candidate_id, eligible_filter)
                .order_by(ApplicationRow.wait_until.asc().nulls_first())
                .limit(limit)
                .all()
            )
            for row in rows:
                row.state = "in_flight"
                row.wait_until = lease_until
                picked.append((row.candidate_id, row.job_id))
        s.commit()

    return picked


def reclaim_expired_leases(candidate_id: str | None = None) -> int:
    """Flip `in_flight` rows whose lease has expired back to `eligible`.

    Runs as a Celery beat task (and is also applied lazily by `pick_work`).
    Returns the count of rows reclaimed.
    """
    now = datetime.utcnow()
    with Session(get_engine()) as s:
        q = s.query(ApplicationRow).filter(
            ApplicationRow.state == "in_flight",
            ApplicationRow.wait_until.isnot(None),
            ApplicationRow.wait_until < now,
        )
        if candidate_id is not None:
            q = q.filter(ApplicationRow.candidate_id == candidate_id)
        rows = q.all()
        for row in rows:
            row.state = "eligible"
            row.wait_until = None
        s.commit()
        return len(rows)


def transition_on_outcome(outcome: ApplyOutcome) -> str:
    """Update the applications ledger based on an ApplyOutcome.

    Creates a row if one does not exist (handles retroactive ingest).
    Returns the new state so callers can log it.
    """
    now = datetime.utcnow()
    with Session(get_engine()) as s:
        row = s.get(ApplicationRow, (outcome.candidate_id, outcome.job_id))
        if row is None:
            row = ApplicationRow(
                candidate_id=outcome.candidate_id,
                job_id=outcome.job_id,
                state="eligible",
            )
            s.add(row)

        status = outcome.status

        if status in ("submitted", "skipped"):
            row.state = "done"
            row.wait_until = None
        elif status == "needs_auth":
            row.state = "abandoned"
            row.wait_until = None
        elif status in ("captcha", "blocked", "interrupted"):
            row.state = "eligible"
            backoff = BACKOFF_BY_STATUS[status]
            row.wait_until = now + backoff if backoff else None
        elif status == "error":
            err_count = (
                s.query(OutcomeRow)
                .filter_by(
                    candidate_id=outcome.candidate_id,
                    job_id=outcome.job_id,
                    status="error",
                )
                .count()
            )
            if err_count >= ABANDON_AFTER_ERRORS:
                row.state = "abandoned"
                row.wait_until = None
            else:
                row.state = "eligible"
                row.wait_until = now + timedelta(seconds=60 * (2 ** err_count))
        # else: unknown status → leave row unchanged

        new_state = row.state
        s.commit()
    return new_state


def list_applications(candidate_id: str | None = None) -> list[dict]:
    """Inspect current ledger rows, ordered by (state, wait_until)."""
    with Session(get_engine()) as s:
        q = s.query(ApplicationRow)
        if candidate_id is not None:
            q = q.filter(ApplicationRow.candidate_id == candidate_id)
        rows = q.order_by(
            ApplicationRow.state.asc(),
            ApplicationRow.wait_until.asc().nulls_last(),
        ).all()
        return [
            {
                "candidate_id": r.candidate_id,
                "job_id": r.job_id,
                "state": r.state,
                "wait_until": r.wait_until.isoformat() if r.wait_until else None,
            }
            for r in rows
        ]


def seed_mock_applications(candidate_id: str = "jason") -> int:
    """Populate the ledger with a variety of states for local testing."""
    now = datetime.utcnow()
    fixtures = [
        # eligible, no backoff — pickable now
        ("job-eligible-fresh-1", "eligible", None),
        ("job-eligible-fresh-2", "eligible", None),
        ("job-eligible-fresh-3", "eligible", None),
        # eligible, backoff hasn't expired — not pickable yet
        ("job-eligible-backoff", "eligible", now + timedelta(hours=8)),
        # in_flight, live lease — skip
        ("job-inflight-live",    "in_flight", now + timedelta(minutes=10)),
        # in_flight, expired lease — pickable (crash recovery)
        ("job-inflight-expired", "in_flight", now - timedelta(minutes=5)),
        # done — never pick again
        ("job-done-submitted",   "done",      None),
        # abandoned — never pick again
        ("job-abandoned",        "abandoned", None),
    ]
    with Session(get_engine()) as s:
        inserted = 0
        for job_id, state, wait_until in fixtures:
            if s.get(ApplicationRow, (candidate_id, job_id)) is None:
                s.add(ApplicationRow(
                    candidate_id=candidate_id,
                    job_id=job_id,
                    state=state,
                    wait_until=wait_until,
                ))
                inserted += 1
        s.commit()
    return inserted


def recent_outcomes(limit: int = 20):
    with Session(get_engine()) as s:
        rows = (
            s.query(OutcomeRow)
            .order_by(OutcomeRow.finished_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "candidate_id": r.candidate_id,
                "job_id": r.job_id,
                "ats": r.ats,
                "status": r.status,
                "message": r.message,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in rows
        ]
