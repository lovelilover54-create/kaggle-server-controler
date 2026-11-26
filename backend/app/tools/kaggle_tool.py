"""Kaggle tools. We call the official `kaggle` CLI (a subprocess) instead of importing the
package: importing it authenticates immediately and crashes when credentials are missing."""
import json
import os
import shutil
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from ..config import get_settings
from ..db import KaggleRun, session_scope, utcnow
from ..kaggle_parse import DATASET, SLUG, TERMINAL, extract_log_text, parse_status, title_from_slug
from ..textutil import redact
from .base import ToolContext, ToolError

MAX_RUN_HOURS = 12  # Kaggle session limit; used to cap runs that were never marked finished


def _bin() -> str:
    exe = shutil.which("kaggle")
    if exe:
        return exe
    cand = os.path.join(os.path.dirname(sys.executable), "kaggle")
    if os.path.exists(cand):
        return cand
    raise ToolError("kaggle CLI not found (pip package 'kaggle' is missing)")


def _run(args, timeout=180):
    try:
        p = subprocess.run([_bin(), *args], capture_output=True, text=True, timeout=timeout, env=os.environ.copy())
    except subprocess.TimeoutExpired:
        raise ToolError("kaggle CLI timed out")
    return p.returncode, redact((p.stdout or "") + (p.stderr or "")).strip()


def _kernel_id(slug: str) -> str:
    if not isinstance(slug, str) or not SLUG.match(slug):
        raise ToolError("slug must be 5-50 chars: lowercase letters, digits, hyphens")
    user = get_settings().kaggle_username
    if not user:
        raise ToolError("KAGGLE_USERNAME is not configured on the server")
    return f"{user}/{slug}"


def _workdir(*parts) -> Path:
    p = Path(get_settings().workdir).joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p


def gpu_hours_used_7d() -> float:
    since = utcnow() - timedelta(days=7)
    total = 0.0
    with session_scope() as s:
        for r in s.scalars(select(KaggleRun).where(KaggleRun.gpu.is_(True), KaggleRun.started_at >= since)):
            end = r.finished_at or utcnow()
            total += min((end - r.started_at).total_seconds(), MAX_RUN_HOURS * 3600)
    return total / 3600


def _mark_state(kernel: str, state: str) -> None:
    with session_scope() as s:
        runs = s.scalars(
            select(KaggleRun).where(KaggleRun.kernel == kernel, KaggleRun.finished_at.is_(None))
        ).all()
        for r in runs:
            r.state = state
            if state in TERMINAL:
                r.finished_at = utcnow()


def status_of(slug: str):
    """Return (normalised_state, raw_text). Also used by the background watcher (no LLM needed)."""
    kernel = _kernel_id(slug)
    code, out = _run(["kernels", "status", kernel], timeout=60)
    state = parse_status(out)
    if code == 0 and state != "unknown":
        _mark_state(kernel, state)
    return state, out


def push_run(ctx: ToolContext, args: dict) -> dict:
    slug = args.get("slug")
    kernel = _kernel_id(slug)
    code_text = args.get("code")
    if not isinstance(code_text, str) or not code_text.strip():
        raise ToolError("code (python source) is required")
    gpu = bool(args.get("gpu", False))
    internet = bool(args.get("internet", True))
    datasets = args.get("dataset_sources") or []
    if not isinstance(datasets, list) or not all(isinstance(d, str) and DATASET.match(d) for d in datasets):
        raise ToolError("dataset_sources must be a list like ['owner/dataset-slug']")
    accelerator = args.get("accelerator")
    if accelerator is not None and not (isinstance(accelerator, str) and accelerator.isalnum()):
        raise ToolError("accelerator must be an alphanumeric id")
    if gpu:
        used = gpu_hours_used_7d()
        cap = get_settings().gpu_weekly_budget_hours
        if used >= cap:
            raise ToolError(f"Agent GPU budget reached ({used:.1f}h of {cap:.0f}h in the last 7 days). Use CPU or ask the owner.")

    d = _workdir("kernels", slug)
    (d / "script.py").write_text(code_text, encoding="utf-8")
    meta = {
        "id": kernel,
        "title": title_from_slug(slug),
        "code_file": "script.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": "true",
        "enable_gpu": "true" if gpu else "false",
        "enable_internet": "true" if internet else "false",
        "dataset_sources": datasets,
        "competition_sources": [],
        "kernel_sources": [],
        "model_sources": [],
    }
    (d / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    cmd = ["kernels", "push", "-p", str(d)]
    if accelerator:
        cmd += ["--accelerator", accelerator]
    code, out = _run(cmd, timeout=240)
    low = out.lower()
    ok = code == 0 and not any(w in low for w in ("error", "failed", "forbidden", "unauthorized", "conflict"))
    if ok:
        with session_scope() as s:
            s.add(KaggleRun(task_id=ctx.task_id, kernel=kernel, gpu=gpu, started_at=utcnow(), state="queued"))
    return {
        "ok": ok,
        "kernel": kernel,
        "url": f"https://www.kaggle.com/code/{kernel}",
        "cli_output": out[:1500],
        "hint": "Next: call wait_for(what='kaggle_kernel', ref=slug), then kaggle_output." if ok else "Push failed; read cli_output.",
    }


def status(ctx: ToolContext, args: dict) -> dict:
    state, raw = status_of(args.get("slug"))
    return {"kernel": _kernel_id(args.get("slug")), "state": state, "raw": raw[:300]}


def output(ctx: ToolContext, args: dict) -> dict:
    slug = args.get("slug")
    kernel = _kernel_id(slug)
    out_dir = Path(get_settings().workdir) / "outputs" / slug
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    code, out = _run(["kernels", "output", kernel, "-p", str(out_dir)], timeout=900)
    files, total, log_text = [], 0, ""
    for p in sorted(out_dir.rglob("*")):
        if not p.is_file():
            continue
        size = p.stat().st_size
        total += size
        if len(files) < 100:
            files.append({"path": str(p.relative_to(out_dir)), "size_kb": round(size / 1024, 1)})
        if p.suffix == ".log" and not log_text:
            try:
                log_text = extract_log_text(p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                pass
    return {
        "ok": code == 0,
        "dir": str(out_dir),
        "files": files,
        "total_mb": round(total / 1e6, 2),
        "log_tail": log_text[-3500:],
        "cli_output": out[:500],
    }


def quota_status(ctx: ToolContext, args: dict) -> dict:
    used = gpu_hours_used_7d()
    cap = get_settings().gpu_weekly_budget_hours
    return {
        "agent_gpu_hours_last_7d": round(used, 2),
        "agent_gpu_budget_hours": cap,
        "note": "Agent-side estimate only. Kaggle's real weekly quota is shown on kaggle.com and has no API.",
    }
