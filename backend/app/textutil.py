"""Small pure helpers: secret redaction, result shrinking, keyword scoring."""
import json
import os
import re

_PATTERNS = [
    re.compile(r"KGAT_[A-Za-z0-9_\-]{8,}"),
    re.compile(r"hf_[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
]
_SECRET_ENV = ("APP_TOKEN", "GEMINI_API_KEY", "KAGGLE_API_TOKEN", "KAGGLE_KEY", "HF_TOKEN", "DATABASE_URL")


def secret_values():
    vals = []
    for name in _SECRET_ENV:
        v = os.getenv(name)
        if not v:
            continue
        if len(v) >= 6:
            vals.append(v)
        # Kaggle token may be the JSON contents of kaggle.json
        try:
            d = json.loads(v)
            if isinstance(d, dict):
                for k in ("key", "token"):
                    if isinstance(d.get(k), str) and len(d[k]) >= 6:
                        vals.append(d[k])
        except Exception:
            pass
    return sorted(set(vals), key=len, reverse=True)


def redact(text):
    """Remove known secrets (and token-shaped strings) from text."""
    if not isinstance(text, str):
        return text
    for v in secret_values():
        text = text.replace(v, "[REDACTED]")
    for p in _PATTERNS:
        text = p.sub("[REDACTED]", text)
    return text


def redact_deep(obj):
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: redact_deep(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_deep(v) for v in obj]
    return obj


def shrink(obj, limit=4000):
    """Clip long strings (keep head and tail) and long lists so tool results stay small."""
    if isinstance(obj, str):
        if len(obj) <= limit:
            return obj
        head = limit * 2 // 3
        tail = limit - head
        return obj[:head] + f"\n...[{len(obj) - limit} chars cut]...\n" + obj[-tail:]
    if isinstance(obj, dict):
        return {k: shrink(v, limit) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        items = [shrink(v, limit) for v in obj[:50]]
        if len(obj) > 50:
            items.append(f"...[{len(obj) - 50} more items]")
        return items
    return obj


def short_args(args, limit=160):
    """Arguments for display in the app: long strings (e.g. code) become a length marker."""
    out = {}
    for k, v in (args or {}).items():
        if isinstance(v, str) and len(v) > limit:
            out[k] = f"<{len(v)} chars>"
        else:
            out[k] = v
    return out


_WORD = re.compile(r"\w+", re.UNICODE)


def tokens(text):
    return {w for w in _WORD.findall((text or "").lower()) if len(w) > 1}


def score(query_tokens, title, body, tags):
    return (
        3 * len(query_tokens & tokens(title))
        + 2 * len(query_tokens & tokens(tags))
        + len(query_tokens & tokens(body))
    )
