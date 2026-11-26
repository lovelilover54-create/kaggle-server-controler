"""Gemini wrapper (google-genai SDK) with manual function calling.

The model's full Content object is stored as JSON and replayed as-is: Gemini 3 models return a
400 error if the thought signatures inside earlier function-call turns are not sent back."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .config import get_settings

log = logging.getLogger("llm")


class LLMError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class LLMResult:
    content_json: str
    text: str
    calls: list


_client = None
_good_model = None


def _get_client():
    global _client
    if _client is None:
        from google import genai

        key = get_settings().gemini_api_key
        if not key:
            raise LLMError("GEMINI_API_KEY is not set on the server")
        _client = genai.Client(api_key=key)
    return _client


def _to_contents(history):
    from google.genai import types

    contents = []
    for h in history:
        if h["role"] == "model":
            contents.append(types.Content.model_validate_json(h["raw"]))
        else:
            parts = []
            for r in h.get("responses", []):
                parts.append(types.Part.from_function_response(name=r["name"], response=r["response"]))
            for t in h.get("text_parts", []):
                parts.append(types.Part.from_text(text=t))
            contents.append(types.Content(role="user", parts=parts))
    return contents


def _parse(resp) -> LLMResult:
    cands = getattr(resp, "candidates", None) or []
    if not cands or cands[0].content is None or not cands[0].content.parts:
        reason = getattr(cands[0], "finish_reason", None) if cands else None
        raise LLMError(f"Empty model response (finish_reason={reason})", retryable=True)
    content = cands[0].content
    text, calls = [], []
    for p in content.parts:
        fc = getattr(p, "function_call", None)
        if fc:
            calls.append({"name": fc.name, "args": dict(fc.args or {})})
        elif getattr(p, "text", None) and not getattr(p, "thought", False):
            text.append(p.text)
    return LLMResult(content.model_dump_json(exclude_none=True), "".join(text).strip(), calls)


def generate(history, system: str, tool_decls) -> LLMResult:
    from google.genai import errors, types

    global _good_model
    cfg = get_settings()
    contents = _to_contents(history)
    config = types.GenerateContentConfig(
        system_instruction=system,
        tools=[types.Tool(function_declarations=[types.FunctionDeclaration(**d) for d in tool_decls])],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    order = list(cfg.gemini_models)
    if _good_model in order:
        order.remove(_good_model)
        order.insert(0, _good_model)
    last = None
    for model in order:
        for attempt in range(4):
            try:
                resp = _get_client().models.generate_content(model=model, contents=contents, config=config)
                result = _parse(resp)
                _good_model = model
                return result
            except errors.APIError as e:
                last = e
                code = getattr(e, "code", None)
                if code == 404:
                    log.warning("model %s not available, trying next", model)
                    break
                if code in (429, 500, 502, 503, 504):
                    time.sleep(min(8 * (attempt + 1), 30))
                    continue
                raise LLMError(f"Gemini API error {code}: {str(e)[:400]}", retryable=False)
            except LLMError as e:
                last = e
                if e.retryable and attempt < 2:
                    time.sleep(3)
                    continue
                raise
            except Exception as e:
                raise LLMError(f"{type(e).__name__}: {str(e)[:400]}", retryable=True)
    raise LLMError("Gemini unavailable: " + str(last)[:300], retryable=True)


def generate_json(prompt: str) -> str:
    """One-shot call used for post-task reflection. Returns the raw JSON text."""
    from google.genai import types

    cfg = get_settings()
    last = None
    for model in cfg.gemini_models:
        try:
            resp = _get_client().models.generate_content(
                model=model, contents=prompt, config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            return resp.text or "[]"
        except Exception as e:
            last = e
    raise LLMError(f"reflection failed: {str(last)[:200]}", retryable=False)
