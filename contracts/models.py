"""Shared, JSON-serializable contracts. Times are source-video seconds."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class Event(Contract):
    id: str = Field(min_length=1)
    time: float = Field(ge=0)
    label: Literal["made", "probable", "missed", "uncertain"]
    evidence: dict[str, Any] = Field(default_factory=dict)

class EditPlan(Contract):
    before_seconds: float = Field(default=5, ge=0, le=60)
    after_seconds: float = Field(default=2, ge=0, le=60)
    excluded_event_ids: list[str] = Field(default_factory=list)

class Operation(Contract):
    op: Literal["set_before", "add_before", "set_after", "add_after", "exclude"]
    value: float | None = Field(default=None, ge=0, le=60)
    ordinal: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_payload(self):
        if self.op == "exclude":
            if self.ordinal is None or self.value is not None:
                raise ValueError("exclude requires ordinal only")
        elif self.value is None or self.ordinal is not None:
            raise ValueError("time operation requires value only")
        return self

class Analysis(Contract):
    events: list[Event]
    duration_seconds: float = Field(gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

class RenderResult(Contract):
    path: str
    duration_seconds: float = Field(gt=0)
    event_ids: list[str]

class Message(Contract):
    id: str
    role: Literal["user", "assistant", "status"]
    text: str
    created_at: str
    request_id: str | None = None

class Result(Contract):
    url: str
    download_url: str
    revision: str

class Job(Contract):
    id: str
    status: Literal["queued", "preparing_roi", "awaiting_roi", "analyzing", "rendering", "completed", "failed", "interrupted"]
    roi: dict[str, Any] | None = None
    events: list[Event] = Field(default_factory=list)
    displayed_event_ids: list[str] = Field(default_factory=list)
    plan: EditPlan = Field(default_factory=EditPlan)
    result: Result | None = None
    error: str | None = None
    candidate_clips: dict[str, dict[str, Any]] = Field(default_factory=dict)


def highlight_eligible(event: Event) -> bool:
    return event.label in ('made','probable') or (event.label=='uncertain' and event.evidence.get('user_selected') is True)
