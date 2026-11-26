"""Turn stored events into model history, and trim it safely.

History items (plain dicts, SDK independent):
  {"role": "user",  "text_parts": [str, ...], "responses": [{"name", "response"}]}
  {"role": "model", "raw": <Content JSON string, keeps Gemini thought signatures>}

Rules that keep the API happy:
  * a model turn with function calls is followed IMMEDIATELY by the user turn holding the responses;
    user text that arrives in between is deferred until after the responses.
  * trimming drops whole (model, responses) pairs, never half a pair, and never user text.
"""
import json


def build_history(events):
    out = []
    deferred = []
    awaiting = False

    def add_text(t):
        if out and out[-1]["role"] == "user":
            out[-1].setdefault("text_parts", []).append(t)
        else:
            out.append({"role": "user", "text_parts": [t]})

    for e in events:
        k = e.kind
        d = e.data or {}
        if k in ("user", "system"):
            text = d.get("text", "")
            if k == "system":
                text = "[system] " + text
            if awaiting:
                deferred.append(text)
            else:
                add_text(text)
        elif k == "model":
            out.append({"role": "model", "raw": d["content_json"]})
            awaiting = bool(d.get("calls"))
        elif k == "tool_result":
            out.append({"role": "user", "responses": d["results"]})
            awaiting = False
            for t in deferred:
                out[-1].setdefault("text_parts", []).append(t)
            deferred = []
    return out


def _size(h):
    return len(json.dumps(h, ensure_ascii=False))


def trim_history(history, max_chars=150_000):
    if sum(_size(h) for h in history) <= max_chars:
        return history
    items = list(history)
    total = sum(_size(h) for h in items)
    drop = set()
    replace = {}
    i = 1  # index 0 is the original goal: always kept
    while total > max_chars and i < len(items) - 2:
        h = items[i]
        if h["role"] == "model":
            total -= _size(h)
            drop.add(i)
            j = i + 1
            if j < len(items) and items[j]["role"] == "user" and items[j].get("responses"):
                texts = items[j].get("text_parts")
                total -= _size(items[j])
                if texts:
                    replace[j] = {"role": "user", "text_parts": texts}
                    total += _size(replace[j])
                else:
                    drop.add(j)
                i = j
        i += 1
    kept = []
    for idx, h in enumerate(items):
        if idx in drop:
            continue
        kept.append(replace.get(idx, h))
    merged = []
    for h in kept:
        if merged and merged[-1]["role"] == "user" and h["role"] == "user" and not h.get("responses") and not merged[-1].get("responses"):
            merged[-1]["text_parts"] = list(merged[-1].get("text_parts", [])) + list(h.get("text_parts", []))
        else:
            merged.append(h)
    if drop and merged and merged[0]["role"] == "user" and not merged[0].get("responses"):
        merged[0]["text_parts"] = list(merged[0].get("text_parts", [])) + [
            "[system] Older steps were trimmed to fit the context window. Use recall / status tools to re-check state if needed."
        ]
    return merged
