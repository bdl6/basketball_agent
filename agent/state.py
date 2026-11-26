"""One-request graph state; business persistence belongs to the backend."""
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    video_path: Path
    work_dir: Path
    model_path: Path
    events: list[dict] | None
    plan: dict
    displayed_event_ids: list[str]
    text: str | None
    pending_context: dict | None
    on_stage: Callable[[str], None]
    interpretation: Any
    result_path: str | None
    message: str
    blocked: bool
