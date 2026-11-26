"""Tool registry. Each tool gets a JSON-schema description for Gemini function calling."""
from .base import ToolContext, ToolSpec
from . import control, hf_tool, kaggle_tool, memory_tool


def _obj(props: dict, required=()):
    return {"type": "object", "properties": props, "required": list(required)}


_S = {"type": "string"}
_B = {"type": "boolean"}
_I = {"type": "integer"}

_SPECS = [
    ToolSpec(
        "kaggle_push_run",
        "Create or update a private Kaggle script kernel from Python source and start it. Outputs must be written to /kaggle/working. "
        "gpu=true needs the owner's approval and uses scarce GPU quota; prefer CPU. Returns the kernel URL.",
        _obj({
            "slug": {"type": "string", "description": "5-50 chars: lowercase letters, digits, hyphens"},
            "code": {"type": "string", "description": "Full Python source of the script"},
            "gpu": _B, "internet": _B,
            "dataset_sources": {"type": "array", "items": _S, "description": "e.g. ['owner/dataset']"},
            "accelerator": _S,
        }, ["slug", "code"]),
        kaggle_tool.push_run),
    ToolSpec("kaggle_status", "Get the state of a kernel: queued, running, complete, error, cancelled.",
             _obj({"slug": _S}, ["slug"]), kaggle_tool.status),
    ToolSpec("kaggle_output",
             "Download a finished kernel's output files to the server and return the file list and the log tail. Use after state is complete or error.",
             _obj({"slug": _S}, ["slug"]), kaggle_tool.output),
    ToolSpec("wait_for",
             "Sleep until a Kaggle kernel or Hugging Face Space reaches a final state. The server watches it for you (no polling needed) and wakes you with the result.",
             _obj({"what": {"type": "string", "enum": ["kaggle_kernel", "hf_space"]}, "ref": {"type": "string", "description": "kernel slug or space name"},
                   "max_minutes": _I}, ["what", "ref"]),
             control.wait_for),
    ToolSpec("quota_status", "Show how many Kaggle GPU hours the agent used in the last 7 days versus its budget.",
             _obj({}), kaggle_tool.quota_status),
    ToolSpec("hf_upload_model",
             "Upload files from a downloaded Kaggle output (see kaggle_output) to a Hugging Face model repo. private=false needs approval.",
             _obj({"repo_name": _S, "kernel_slug": _S, "subdir": _S, "private": _B, "delete_local": _B}, ["repo_name", "kernel_slug"]),
             hf_tool.upload_model),
    ToolSpec("hf_deploy_space",
             "Create/update a Hugging Face Gradio Space (free CPU) that serves a model through a /predict API. Private by default; "
             "private=false or needs_token=true needs approval.",
             _obj({"space_name": _S, "model_id": {"type": "string", "description": "e.g. 'Qwen/Qwen2.5-0.5B-Instruct' or 'user/my-model'"},
                   "task": {"type": "string", "enum": sorted(hf_tool._TASKS)}, "private": _B, "needs_token": _B}, ["space_name", "model_id"]),
             hf_tool.deploy_space),
    ToolSpec("hf_space_status", "Get the build/run stage of a Space (BUILDING, RUNNING, BUILD_ERROR, RUNTIME_ERROR...).",
             _obj({"space_name": _S}, ["space_name"]), hf_tool.space_status),
    ToolSpec("hf_space_predict",
             "Call a running Space's Gradio API to verify it works. inputs_json is a JSON array, e.g. [\"Hello\", 64].",
             _obj({"space_name": _S, "inputs_json": _S, "api_name": _S}, ["space_name", "inputs_json"]),
             hf_tool.space_predict),
    ToolSpec("recall", "Search long-term memory (lessons, skills, facts) by keywords.",
             _obj({"query": _S}, ["query"]), memory_tool.recall),
    ToolSpec("save_lesson",
             "Save a verified lesson (what went wrong or what is true) so future tasks avoid the mistake. evidence is required.",
             _obj({"title": _S, "body": _S, "evidence": _S}, ["title", "body", "evidence"]), memory_tool.save_lesson),
    ToolSpec("save_skill",
             "Save a repeatable procedure as a draft skill. It becomes active after the owner approves it in the app.",
             _obj({"name": _S, "when_to_use": _S, "steps": _S}, ["name", "when_to_use", "steps"]), memory_tool.save_skill),
    ToolSpec("ask_user", "Ask the owner ONE clear question and pause until they answer.",
             _obj({"question": _S}, ["question"]), control.ask_user),
    ToolSpec("finish_task",
             "End the task. Only after verifying the result with evidence. summary: short, with URLs and how to use the result.",
             _obj({"summary": _S, "success": _B}, ["summary"]), control.finish_task),
]

REGISTRY = {s.name: s for s in _SPECS}


def declarations():
    return [{"name": s.name, "description": s.description, "parameters": s.parameters} for s in _SPECS]


def approval_reason(tool: str, args: dict, auto_approve: bool):
    """Return a reason string if this call needs the owner's approval, else None."""
    args = args or {}
    if tool == "hf_deploy_space" and args.get("needs_token"):
        return "Stores your Hugging Face token as a secret inside the Space"
    if auto_approve:
        return None
    if tool == "kaggle_push_run" and args.get("gpu"):
        return "Uses Kaggle GPU quota"
    if tool in ("hf_deploy_space", "hf_upload_model") and args.get("private", True) is False:
        return "Makes the repository public"
    return None
