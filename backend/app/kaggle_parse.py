"""Pure parsing helpers for Kaggle CLI output."""
import json
import re

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{4,49}$")  # Kaggle needs a title of 5+ characters
DATASET = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
TERMINAL = {"complete", "error", "cancelled"}

_STATUS = re.compile(r'has status\s+"?([^"\n]+?)"?\s*$', re.I | re.M)


def parse_status(text):
    """Normalise `kaggle kernels status` output to: queued/running/complete/error/cancelled/unknown."""
    m = _STATUS.search(text or "")
    raw = (m.group(1) if m else "").strip().lower().split(".")[-1]
    if "complete" in raw:
        return "complete"
    if "error" in raw or "fail" in raw:
        return "error"
    if "cancel" in raw:
        return "cancelled"
    if "run" in raw:
        return "running"
    if "queue" in raw or "new" in raw:
        return "queued"
    return "unknown"


def extract_log_text(raw):
    """Kaggle writes the run log as a JSON list of {stream_name, time, data}. Return plain text."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except Exception:
        return raw
    if isinstance(data, list):
        return "".join(item.get("data", "") if isinstance(item, dict) else str(item) for item in data)
    return raw


def title_from_slug(slug):
    """Kaggle derives the slug from the title, so the title must slugify back to the same slug."""
    return slug.replace("-", " ").title()
