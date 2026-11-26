"""Long-term memory: facts, lessons (with evidence) and skills (draft until the owner approves)."""
from sqlalchemy import select

from ..db import Memory, session_scope, utcnow
from ..textutil import score, tokens
from .base import ToolContext, ToolError


def search(query: str, limit: int = 6, kinds=None):
    q = tokens(query)
    if not q:
        return []
    with session_scope() as s:
        stmt = select(Memory).where(Memory.status.in_(("active", "draft")))
        if kinds:
            stmt = stmt.where(Memory.kind.in_(kinds))
        rows = s.scalars(stmt).all()
        scored = sorted(
            ((score(q, r.title, r.body, r.tags) * (0.7 if r.status == "draft" else 1.0), r) for r in rows),
            key=lambda x: x[0],
            reverse=True,
        )
        out = [r for sc, r in scored[:limit] if sc > 0]
        for r in out:
            r.uses += 1
        return [
            {"id": r.id, "kind": r.kind, "title": r.title, "body": r.body, "status": r.status, "evidence": r.evidence}
            for r in out
        ]


def memory_block(query: str) -> str:
    rows = search(query, limit=6)
    if not rows:
        return ""
    lines = ["", "", "RELEVANT MEMORY (earlier lessons and skills; trust but verify):"]
    for r in rows:
        tag = r["kind"] + ("/draft" if r["status"] == "draft" else "")
        lines.append(f"- [{tag}] {r['title']}: {r['body'][:700]}")
    return "\n".join(lines)


def recall(ctx: ToolContext, args: dict) -> dict:
    return {"matches": search(str(args.get("query", "")), limit=5)}


def upsert(kind: str, title: str, body: str, evidence: str = "", status: str = "active",
           tags: str = "", source: str = "agent", confidence: float = 0.6) -> int:
    with session_scope() as s:
        row = s.scalars(select(Memory).where(Memory.kind == kind, Memory.title.ilike(title))).first()
        if row:
            row.body, row.evidence, row.updated_at = body, evidence or row.evidence, utcnow()
            row.version += 1
            if row.status == "archived":
                row.status = status
        else:
            row = Memory(kind=kind, title=title[:200], body=body, evidence=evidence, status=status,
                         tags=tags[:300], source=source, confidence=confidence)
            s.add(row)
        s.flush()
        return row.id


def save_lesson(ctx: ToolContext, args: dict) -> dict:
    title, body, evidence = (str(args.get(k, "")).strip() for k in ("title", "body", "evidence"))
    if not title or not body:
        raise ToolError("title and body are required")
    if len(evidence) < 10:
        raise ToolError("evidence is required (quote the error or the observation that proves the lesson)")
    return {"saved": True, "id": upsert("lesson", title, body, evidence=evidence)}


def save_skill(ctx: ToolContext, args: dict) -> dict:
    name, when, steps = (str(args.get(k, "")).strip() for k in ("name", "when_to_use", "steps"))
    if not name or not when or not steps:
        raise ToolError("name, when_to_use and steps are required")
    body = f"WHEN: {when}\nSTEPS:\n{steps}"
    return {"saved": True, "status": "draft (needs the owner's approval in the app)", "id": upsert("skill", name, body, status="draft")}
