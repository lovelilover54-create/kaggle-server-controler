"""Background scheduler. Runs inside the web process (one Render service, one uvicorn worker).

* picks up queued tasks and runs them in a small thread pool
* watches sleeping tasks (Kaggle kernels / HF Spaces) WITHOUT calling the LLM, and wakes them when done
* on startup, resumes tasks that were interrupted by a restart"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from sqlalchemy import select, update

from .agent import run_task
from .config import get_settings
from .db import Task, add_event, get_setting, session_scope, utcnow

log = logging.getLogger("worker")
KAGGLE_DONE = {"complete", "error", "cancelled"}
SPACE_DONE = {"RUNNING", "RUNTIME_ERROR", "BUILD_ERROR", "CONFIG_ERROR", "NO_APP_FILE", "STOPPED", "PAUSED", "DELETING"}


def recover() -> None:
    """Tasks that were 'running' when the server stopped go back to the queue."""
    with session_scope() as s:
        for t in s.scalars(select(Task).where(Task.status == "running")):
            t.status = "queued"
            add_event(s, t.id, "note", {"text": "Server restarted. Resuming."})


def _poll(watch: dict):
    """Return (finished, message). Never raises."""
    try:
        if watch["what"] == "kaggle_kernel":
            from .tools.kaggle_tool import status_of

            state, _ = status_of(watch["ref"])
            return state in KAGGLE_DONE, f"Kaggle kernel '{watch['ref']}' state: {state}. Call kaggle_status / kaggle_output next."
        from .tools.hf_tool import space_stage

        info = space_stage(watch["ref"])
        return info["stage"] in SPACE_DONE, f"Space '{info['space']}' stage: {info['stage']}. App URL: {info['app_url']}"
    except Exception as e:
        log.warning("watch poll failed: %s", e)
        return False, f"watch check failed: {e}"


class Worker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="agent-worker")
        self.cfg = get_settings()
        self.stop_event = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=self.cfg.max_concurrent_tasks)
        self.running: set = set()
        self.lock = threading.Lock()

    def run(self):
        while not self.stop_event.is_set():
            try:
                self._wake_sleepers()
                self._claim()
            except Exception:
                log.exception("scheduler tick failed")
            self.stop_event.wait(5)

    def stop(self):
        self.stop_event.set()
        self.pool.shutdown(wait=False, cancel_futures=True)

    def _requeue(self, task_id: str, message: str | None):
        with session_scope() as s:
            t = s.get(Task, task_id)
            if t is None or t.status != "sleeping":
                return
            t.status, t.watch, t.wake_at, t.updated_at = "queued", None, None, utcnow()
            if message:
                add_event(s, task_id, "system", {"text": message})

    def _wake_sleepers(self):
        now = utcnow()
        with session_scope() as s:
            items = [(t.id, t.wake_at, t.watch) for t in s.scalars(select(Task).where(Task.status == "sleeping"))]
        for tid, wake_at, watch in items:
            if not watch:
                if wake_at is None or now >= wake_at:
                    self._requeue(tid, None)
                continue
            if now < datetime.fromisoformat(watch["next_check"]):
                continue
            done, msg = _poll(watch)
            if done:
                self._requeue(tid, msg)
            elif now >= datetime.fromisoformat(watch["deadline"]):
                self._requeue(tid, f"Waiting timed out after {watch['max_minutes']} min. Last: {msg}")
            else:
                interval = min(int(watch.get("interval", 45) * 1.5), 300)
                w = dict(watch, interval=interval, next_check=(now + timedelta(seconds=interval)).isoformat())
                with session_scope() as s:
                    t = s.get(Task, tid)
                    if t is not None and t.status == "sleeping":
                        t.watch = w

    def _claim(self):
        with session_scope() as s:
            if get_setting(s, "paused") == "1":
                return
            ids = list(s.scalars(select(Task.id).where(Task.status == "queued").order_by(Task.updated_at)))
        for tid in ids:
            with self.lock:
                if tid in self.running or len(self.running) >= self.cfg.max_concurrent_tasks:
                    continue
            with session_scope() as s:
                res = s.execute(update(Task).where(Task.id == tid, Task.status == "queued").values(status="running", updated_at=utcnow()))
                if res.rowcount != 1:
                    continue
            with self.lock:
                self.running.add(tid)
            self.pool.submit(self._run, tid)

    def _run(self, tid: str):
        try:
            run_task(tid)
        finally:
            with self.lock:
                self.running.discard(tid)
            with session_scope() as s:
                t = s.get(Task, tid)
                if t is not None and t.status == "running":
                    t.status = "waiting_user"  # should not happen; never leave a task 'running' forever
