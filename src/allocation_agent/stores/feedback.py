from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import StaticPool

from ..config import settings
from ..schemas import ApplyOutcome, CallbackSignal


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
