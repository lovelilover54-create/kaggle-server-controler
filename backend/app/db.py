"""Database models. Postgres on Render, SQLite for local dev.

No migrations in this MVP: tables are created on startup. When you change a model later,
add Alembic or drop the table (dev only).
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    # queued | running | sleeping | waiting_approval | waiting_user | done | failed | stopped
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    auto_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    wake_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    watch: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    pending: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(32), index=True)
    # user | system | model | tool_result | note | approval | ask | final
    kind: Mapped[str] = mapped_column(String(20))
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(32), index=True)
    tool: Mapped[str] = mapped_column(String(60))
    args: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending | approved | rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Memory(Base):
    __tablename__ = "memory"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(10), index=True)  # fact | lesson | skill
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    tags: Mapped[str] = mapped_column(String(300), default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | draft | archived
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    source: Mapped[str] = mapped_column(String(10), default="agent")  # seed | agent | user
    version: Mapped[int] = mapped_column(Integer, default=1)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class KaggleRun(Base):
    """Agent-side record of Kaggle runs, used for a GPU-hours safety cap (not Kaggle's real quota)."""

    __tablename__ = "kaggle_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(32))
    kernel: Mapped[str] = mapped_column(String(120), index=True)
    gpu: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    state: Mapped[str] = mapped_column(String(20), default="queued")


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(300), default="")


_settings = get_settings()
_kwargs = {"pool_pre_ping": True}
if _settings.database_url.startswith("sqlite"):
    _kwargs["connect_args"] = {"check_same_thread": False}
engine = create_engine(_settings.database_url, **_kwargs)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


@contextlib.contextmanager
def session_scope():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def add_event(s, task_id: str, kind: str, data: dict) -> Event:
    e = Event(task_id=task_id, kind=kind, data=data, created_at=utcnow())
    s.add(e)
    s.flush()
    return e


def get_setting(s, key: str, default: str = "") -> str:
    row = s.get(Setting, key)
    return row.value if row else default


def set_setting(s, key: str, value: str) -> None:
    row = s.get(Setting, key)
    if row:
        row.value = value
    else:
        s.add(Setting(key=key, value=value))


def last_user_text(s, task_id: str) -> str:
    e = s.scalars(
        select(Event).where(Event.task_id == task_id, Event.kind == "user").order_by(Event.id.desc()).limit(1)
    ).first()
    return (e.data or {}).get("text", "") if e else ""
