"""Hugging Face tools: upload models, deploy a Gradio Space that serves a model, check it, call it."""
import json
import re
import shutil
import textwrap
from pathlib import Path

from ..config import get_settings
from ..kaggle_parse import SLUG
from ..textutil import redact
from .base import ToolContext, ToolError

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,60}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
_TASKS = {"text-generation", "text-classification", "summarization", "translation", "fill-mask", "sentiment-analysis"}
_owner = None


def _api():
    from huggingface_hub import HfApi

    token = get_settings().hf_token
    if not token:
        raise ToolError("HF_TOKEN is not configured on the server")
    return HfApi(token=token)


def _owner_name() -> str:
    global _owner
    if _owner is None:
        try:
            _owner = _api().whoami()["name"]
        except Exception as e:
            raise ToolError(f"Hugging Face login failed: {redact(str(e))[:200]}")
    return _owner


def _name(value, what):
    if not isinstance(value, str) or not _NAME.match(value):
        raise ToolError(f"{what} must be 2-61 chars: letters, digits, . _ -")
    return value


def _space_url(repo_id: str) -> str:
    owner, name = repo_id.split("/", 1)
    host = f"{owner}-{name}".lower().replace("_", "-").replace(".", "-")
    return f"https://{host}.hf.space"


APP_TEMPLATE = '''import os
import gradio as gr
from transformers import pipeline

MODEL_ID = "{model_id}"
TASK = "{task}"
pipe = pipeline(TASK, model=MODEL_ID, token=os.environ.get("HF_TOKEN"))


def predict(prompt, max_new_tokens=128):
    if TASK in ("text-generation", "summarization", "translation"):
        key = "max_new_tokens" if TASK == "text-generation" else "max_length"
        return pipe(prompt, **{{key: int(max_new_tokens)}})
    return pipe(prompt)


demo = gr.Interface(
    fn=predict,
    inputs=[gr.Textbox(label="Input"), gr.Slider(1, 512, value=128, step=1, label="Max new tokens")],
    outputs=gr.JSON(),
    api_name="predict",
)
demo.launch()
'''


def deploy_space(ctx: ToolContext, args: dict) -> dict:
    from huggingface_hub import CommitOperationAdd

    space_name = _name(args.get("space_name"), "space_name")
    model_id = args.get("model_id")
    task = args.get("task", "text-generation")
    private = args.get("private", True) is not False
    needs_token = bool(args.get("needs_token", False))
    if not isinstance(model_id, str) or not _MODEL_ID.match(model_id):
        raise ToolError("model_id must look like 'owner/name'")
    if task not in _TASKS:
        raise ToolError(f"task must be one of {sorted(_TASKS)}")
    api = _api()
    try:
        api.model_info(model_id)
    except Exception as e:
        raise ToolError(f"Model '{model_id}' not found or not accessible: {redact(str(e))[:200]}")

    repo_id = f"{_owner_name()}/{space_name}"
    readme = textwrap.dedent(
        f"""\
        ---
        title: {space_name}
        emoji: 🤖
        colorFrom: blue
        colorTo: indigo
        sdk: gradio
        app_file: app.py
        pinned: false
        ---
        Model host created by the agent. Model: {model_id}
        """
    )
    try:
        api.create_repo(repo_id=repo_id, repo_type="space", space_sdk="gradio", private=private, exist_ok=True)
        api.create_commit(
            repo_id=repo_id,
            repo_type="space",
            operations=[
                CommitOperationAdd("README.md", readme.encode()),
                CommitOperationAdd("app.py", APP_TEMPLATE.format(model_id=model_id, task=task).encode()),
                CommitOperationAdd("requirements.txt", b"transformers\ntorch\naccelerate\n"),
            ],
            commit_message="Deploy model host (agent)",
        )
        if needs_token:
            api.add_space_secret(repo_id=repo_id, key="HF_TOKEN", value=get_settings().hf_token)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Space deploy failed: {redact(str(e))[:400]}")
    return {
        "ok": True,
        "space": repo_id,
        "page": f"https://huggingface.co/spaces/{repo_id}",
        "app_url": _space_url(repo_id),
        "private": private,
        "next": "call wait_for(what='hf_space', ref=space_name); first build can take several minutes",
    }


def space_stage(space_name: str) -> dict:
    repo_id = f"{_owner_name()}/{_name(space_name, 'space_name')}"
    try:
        rt = _api().get_space_runtime(repo_id)
    except Exception as e:
        raise ToolError(f"Cannot read Space status: {redact(str(e))[:300]}")
    stage = getattr(rt.stage, "value", rt.stage)
    return {"space": repo_id, "stage": str(stage), "hardware": str(getattr(rt, "hardware", None)), "app_url": _space_url(repo_id)}


def space_status(ctx: ToolContext, args: dict) -> dict:
    return space_stage(args.get("space_name"))


def upload_model(ctx: ToolContext, args: dict) -> dict:
    repo_name = _name(args.get("repo_name"), "repo_name")
    slug = args.get("kernel_slug")
    if not isinstance(slug, str) or not SLUG.match(slug):
        raise ToolError("kernel_slug is invalid")
    private = args.get("private", True) is not False
    root = (Path(get_settings().workdir) / "outputs" / slug).resolve()
    if not root.exists():
        raise ToolError("No downloaded output for that kernel. Call kaggle_output first.")
    src = root
    subdir = args.get("subdir")
    if subdir:
        src = (root / subdir).resolve()
        if root not in src.parents and src != root:
            raise ToolError("subdir must stay inside the kernel output")
        if not src.exists():
            raise ToolError("subdir does not exist in the output")
    repo_id = f"{_owner_name()}/{repo_name}"
    api = _api()
    try:
        api.create_repo(repo_id=repo_id, repo_type="model", private=private, exist_ok=True)
        api.upload_folder(
            folder_path=str(src),
            repo_id=repo_id,
            repo_type="model",
            commit_message="Upload from Kaggle output (agent)",
            ignore_patterns=["*.log", "__pycache__/*"],
        )
    except Exception as e:
        raise ToolError(f"Upload failed: {redact(str(e))[:400]}")
    if args.get("delete_local", True) is not False:
        shutil.rmtree(root, ignore_errors=True)
    return {"ok": True, "model_id": repo_id, "private": private, "page": f"https://huggingface.co/{repo_id}"}


def space_predict(ctx: ToolContext, args: dict) -> dict:
    from gradio_client import Client

    repo_id = f"{_owner_name()}/{_name(args.get('space_name'), 'space_name')}"
    try:
        inputs = json.loads(args.get("inputs_json", "[]"))
    except Exception:
        raise ToolError("inputs_json must be a JSON array, e.g. [\"Hello\", 64]")
    if not isinstance(inputs, list):
        raise ToolError("inputs_json must be a JSON array")
    api_name = args.get("api_name", "/predict")
    token = get_settings().hf_token
    try:
        try:
            client = Client(repo_id, hf_token=token)
        except TypeError:
            client = Client(repo_id, token=token)
        result = client.submit(*inputs, api_name=api_name).result(timeout=180)
    except Exception as e:
        raise ToolError(f"Prediction call failed: {redact(str(e))[:500]}")
    return {"ok": True, "result": json.loads(json.dumps(result, default=str))}
