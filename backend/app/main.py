"""HTTP API for the mobile app. Everything except /health needs  Authorization: Bearer <APP_TOKEN>."""
from __future__ import annotations

import logging
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select

from .config import get_settings
from .db import Approval, Event, Memory, Task, add_event, get_setting, init_db, session_scope, set_setting, utcnow
from .skills_seed import SEED_SKILLS
from .textutil import redact_deep
from .worker import Worker, recover

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")
_bearer = HTTPBearer(auto_error=False)
_worker: Worker | None = None


def _seed() -> None:
    with session_scope() as s:
        for title, when, steps in SEED_SKILLS:
            exists = s.scalars(select(Memory).where(Memory.kind == "skill", Memory.title == title)).first()
            if not exists:
                s.add(Memory(kind="skill", title=title, body=f"WHEN: {when}\nSTEPS:\n{steps}", status="active", source="seed", confidence=0.8))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _worker
    if not get_settings().app_token or len(get_settings().app_token) < 16:
        raise RuntimeError("Set APP_TOKEN to a random string of at least 16 characters")
    init_db()
    _seed()
    recover()
    _worker = Worker()
    _worker.start()
    log.info("worker started")
    yield
    if _worker:
        _worker.stop()


app = FastAPI(title="Agent backend", lifespan=lifespan)


def auth(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    token = get_settings().app_token
    if cred is None or not secrets.compare_digest(cred.credentials.encode(), token.encode()):
        raise HTTPException(status_code=401, detail="Invalid token")


def iso(dt: datetime | None) -> str | None:
    return dt.replace(tzinfo=timezone.utc).isoformat() if dt else None


# ---------------------------------------------------------------- serializers
def ui_event(e: Event) -> dict:
    d = e.data or {}
    base = {"id": e.id, "at": iso(e.created_at)}
    if e.kind == "user":
        return {**base, "kind": "user", "text": d.get("text", "")}
    if e.kind == "model":
        calls = [{"name": c["name"]} for c in d.get("calls", [])]
        return {**base, "kind": "assistant", "text": redact_deep(d.get("text", "")), "calls": calls}
    if e.kind == "tool_result":
        return {**base, "kind": "tool", "items": redact_deep(d.get("ui", []))}
    if e.kind in ("final", "ask", "note"):
        return {**base, "kind": e.kind, "text": redact_deep(d.get("text", "")), "success": d.get("success", True)}
    if e.kind == "approval":
        return {**base, "kind": "approval", "approval_id": d.get("approval_id"), "tool": d.get("tool"), "args": d.get("args", {}), "reason": d.get("reason", "")}
    return {**base, "kind": "hidden"}  # system events are for the model only


def task_dict(s, t: Task, preview: bool = False) -> dict:
    d = {
        "id": t.id, "title": t.title, "status": t.status, "auto_approve": t.auto_approve,
        "summary": t.summary, "created_at": iso(t.created_at), "updated_at": iso(t.updated_at),
        "pending_approvals": list(s.scalars(select(Approval.id).where(Approval.task_id == t.id, Approval.status == "pending"))),
    }
    if preview:
        last = s.scalars(select(Event).where(Event.task_id == t.id, Event.kind.in_(("user", "model", "final", "ask", "note"))).order_by(Event.id.desc()).limit(6)).all()
        d["preview"] = next(((x.data or {}).get("text", "") for x in last if (x.data or {}).get("text")), "")[:140]
    return d


def _task_or_404(s, task_id: str) -> Task:
    t = s.get(Task, task_id)
    if t is None:
        raise HTTPException(404, "Task not found")
    return t


# ---------------------------------------------------------------- models
class NewTask(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class Msg(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class Flag(BaseModel):
    value: bool


class Decision(BaseModel):
    approve: bool


class MemoryPatch(BaseModel):
    status: str = Field(pattern="^(active|draft|archived)$")


class NewMemory(BaseModel):
    kind: str = Field(pattern="^(fact|lesson)$")
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)


# ---------------------------------------------------------------- routes
@app.get("/health")
def health():
    return {"ok": True}


@app.get("/tasks", dependencies=[Depends(auth)])
def list_tasks(limit: int = Query(50, ge=1, le=200)):
    with session_scope() as s:
        rows = s.scalars(select(Task).order_by(Task.updated_at.desc()).limit(limit)).all()
        return [task_dict(s, t, preview=True) for t in rows]


@app.post("/tasks", dependencies=[Depends(auth)])
def create_task(body: NewTask):
    tid = uuid.uuid4().hex
    text = body.message.strip()
    with session_scope() as s:
        s.add(Task(id=tid, title=text[:60], status="queued", created_at=utcnow(), updated_at=utcnow()))
        s.flush()
        add_event(s, tid, "user", {"text": text})
        return task_dict(s, s.get(Task, tid))


@app.get("/tasks/{task_id}", dependencies=[Depends(auth)])
def get_task(task_id: str):
    with session_scope() as s:
        return task_dict(s, _task_or_404(s, task_id))


@app.get("/tasks/{task_id}/events", dependencies=[Depends(auth)])
def get_events(task_id: str, after: int = 0):
    with session_scope() as s:
        _task_or_404(s, task_id)
        rows = s.scalars(select(Event).where(Event.task_id == task_id, Event.id > after).order_by(Event.id).limit(300)).all()
        return [ui_event(e) for e in rows]


@app.post("/tasks/{task_id}/messages", dependencies=[Depends(auth)])
def post_message(task_id: str, body: Msg):
    with session_scope() as s:
        t = _task_or_404(s, task_id)
        add_event(s, task_id, "user", {"text": body.message.strip()})
        if t.status in ("done", "failed", "stopped", "waiting_user", "sleeping"):
            t.status, t.watch, t.wake_at = "queued", None, None
        t.updated_at = utcnow()
        return task_dict(s, t)


@app.post("/tasks/{task_id}/stop", dependencies=[Depends(auth)])
def stop_task(task_id: str):
    with session_scope() as s:
        t = _task_or_404(s, task_id)
        t.status, t.watch, t.wake_at, t.pending, t.updated_at = "stopped", None, None, None, utcnow()
        for ap in s.scalars(select(Approval).where(Approval.task_id == task_id, Approval.status == "pending")):
            ap.status, ap.resolved_at = "rejected", utcnow()
        add_event(s, task_id, "note", {"text": "Stopped by you."})
        return task_dict(s, t)


@app.post("/tasks/{task_id}/auto_approve", dependencies=[Depends(auth)])
def set_auto_approve(task_id: str, body: Flag):
    with session_scope() as s:
        t = _task_or_404(s, task_id)
        t.auto_approve = body.value
        add_event(s, task_id, "note", {"text": "Auto-approve is " + ("ON for this chat." if body.value else "OFF.")})
        return task_dict(s, t)


@app.post("/approvals/{approval_id}", dependencies=[Depends(auth)])
def resolve_approval(approval_id: int, body: Decision):
    with session_scope() as s:
        ap = s.get(Approval, approval_id)
        if ap is None:
            raise HTTPException(404, "Approval not found")
        if ap.status != "pending":
            raise HTTPException(409, "Already resolved")
        ap.status, ap.resolved_at = ("approved" if body.approve else "rejected"), utcnow()
        t = s.get(Task, ap.task_id)
        if t and t.status == "waiting_approval":
            t.status, t.updated_at = "queued", utcnow()
        add_event(s, ap.task_id, "note", {"text": ("Approved: " if body.approve else "Rejected: ") + ap.tool})
        return {"id": ap.id, "status": ap.status}


@app.get("/memory", dependencies=[Depends(auth)])
def list_memory(kind: str | None = None, status: str | None = None):
    with session_scope() as s:
        stmt = select(Memory).order_by(Memory.updated_at.desc()).limit(300)
        if kind:
            stmt = stmt.where(Memory.kind == kind)
        stmt = stmt.where(Memory.status == status) if status else stmt.where(Memory.status != "archived")
        return [
            {"id": m.id, "kind": m.kind, "title": m.title, "body": m.body, "status": m.status, "source": m.source,
             "evidence": m.evidence, "uses": m.uses, "version": m.version, "updated_at": iso(m.updated_at)}
            for m in s.scalars(stmt)
        ]


@app.post("/memory", dependencies=[Depends(auth)])
def add_memory(body: NewMemory):
    with session_scope() as s:
        m = Memory(kind=body.kind, title=body.title, body=body.body, status="active", source="user", confidence=0.9)
        s.add(m)
        s.flush()
        return {"id": m.id}


@app.patch("/memory/{memory_id}", dependencies=[Depends(auth)])
def patch_memory(memory_id: int, body: MemoryPatch):
    with session_scope() as s:
        m = s.get(Memory, memory_id)
        if m is None:
            raise HTTPException(404, "Not found")
        m.status, m.updated_at = body.status, utcnow()
        return {"id": m.id, "status": m.status}


@app.delete("/memory/{memory_id}", dependencies=[Depends(auth)])
def delete_memory(memory_id: int):
    with session_scope() as s:
        m = s.get(Memory, memory_id)
        if m is not None:
            s.delete(m)
        return {"ok": True}


@app.get("/control", dependencies=[Depends(auth)])
def control_state():
    from .tools.kaggle_tool import gpu_hours_used_7d

    with session_scope() as s:
        paused = get_setting(s, "paused") == "1"
    return {"paused": paused, "gpu_hours_7d": round(gpu_hours_used_7d(), 2), "gpu_budget_hours": get_settings().gpu_weekly_budget_hours}


@app.post("/control/pause", dependencies=[Depends(auth)])
def pause_all():
    with session_scope() as s:
        set_setting(s, "paused", "1")
    return {"paused": True}


@app.post("/control/resume", dependencies=[Depends(auth)])
def resume_all():
    with session_scope() as s:
        set_setting(s, "paused", "0")
    return {"paused": False}


@app.post("/control/kill", dependencies=[Depends(auth)])
def kill_all():
    """Kill switch: pause the scheduler and stop every unfinished task."""
    with session_scope() as s:
        set_setting(s, "paused", "1")
        n = 0
        for t in s.scalars(select(Task).where(Task.status.in_(("queued", "running", "sleeping", "waiting_approval", "waiting_user")))):
            t.status, t.watch, t.wake_at, t.pending, t.updated_at = "stopped", None, None, None, utcnow()
            add_event(s, t.id, "note", {"text": "Stopped by the kill switch."})
            n += 1
        for ap in s.scalars(select(Approval).where(Approval.status == "pending")):
            ap.status, ap.resolved_at = "rejected", utcnow()
    return {"paused": True, "stopped_tasks": n}
