import os
from dataclasses import dataclass
from functools import lru_cache


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip() or "sqlite:///./dev.db"
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    app_token: str
    database_url: str
    gemini_api_key: str
    gemini_models: tuple
    kaggle_username: str
    hf_token: str
    workdir: str
    max_steps_per_run: int
    max_tool_errors: int
    max_concurrent_tasks: int
    max_context_chars: int
    gpu_weekly_budget_hours: float


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    models = os.getenv("GEMINI_MODELS", "gemini-3.7-flash,gemini-3.6-flash,gemini-3.5-flash,gemini-2.5-flash")
    return Settings(
        app_token=os.getenv("APP_TOKEN", "").strip(),
        database_url=_database_url(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_models=tuple(m.strip() for m in models.split(",") if m.strip()),
        kaggle_username=os.getenv("KAGGLE_USERNAME", "").strip(),
        hf_token=os.getenv("HF_TOKEN", "").strip(),
        workdir=os.getenv("WORKDIR", "/tmp/agent"),
        max_steps_per_run=_int("MAX_STEPS_PER_RUN", 40),
        max_tool_errors=_int("MAX_TOOL_ERRORS", 6),
        max_concurrent_tasks=_int("MAX_CONCURRENT_TASKS", 2),
        max_context_chars=_int("MAX_CONTEXT_CHARS", 150_000),
        gpu_weekly_budget_hours=_float("GPU_WEEKLY_BUDGET_HOURS", 20.0),
    )
