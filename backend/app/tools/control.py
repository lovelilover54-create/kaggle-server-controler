"""Control-flow tools. They return a '_signal' that the agent loop acts on."""
from ..kaggle_parse import SLUG
from .base import ToolContext, ToolError



def finish_task(ctx: ToolContext, args: dict) -> dict:
    summary = str(args.get("summary", "")).strip()
    if not summary:
        raise ToolError("summary is required")
    return {"status": "recorded", "_signal": {"type": "finish", "summary": summary, "success": bool(args.get("success", True))}}


def ask_user(ctx: ToolContext, args: dict) -> dict:
    q = str(args.get("question", "")).strip()
    if not q:
        raise ToolError("question is required")
    return {"status": "asked", "_signal": {"type": "ask", "question": q}}


def wait_for(ctx: ToolContext, args: dict) -> dict:
    what = args.get("what")
    ref = args.get("ref")
    try:
        minutes = int(args.get("max_minutes", 90))
    except (TypeError, ValueError):
        minutes = 90
    minutes = max(1, min(minutes, 720))
    if what == "kaggle_kernel":
        if not isinstance(ref, str) or not SLUG.match(ref):
            raise ToolError("ref must be the kernel slug")
    elif what == "hf_space":
        if not isinstance(ref, str) or not ref:
            raise ToolError("ref must be the space name")
    else:
        raise ToolError("what must be 'kaggle_kernel' or 'hf_space'")
    return {
        "status": "sleeping",
        "message": f"Task sleeps until {what} {ref} finishes (max {minutes} min). You will be woken with the result.",
        "_signal": {"type": "sleep", "watch": {"what": what, "ref": ref, "max_minutes": minutes}},
    }
