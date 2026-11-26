from dataclasses import dataclass
from typing import Any, Callable


class ToolError(Exception):
    """An expected failure the agent should read and react to."""


@dataclass
class ToolContext:
    task_id: str


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    fn: Callable[[ToolContext, dict], Any]
