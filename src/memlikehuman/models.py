"""Validated public data types. Event roles are asserted by the submitting host."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def timestamp(value: str | None) -> str:
    if value is None:
        return now()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamps must include a timezone")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Scope(Model):
    persona_id: str = Field(default="default", min_length=1, max_length=100, pattern=r"^[\w.-]+$")
    project_id: str = Field(default="default", min_length=1, max_length=100, pattern=r"^[\w.-]+$")


class Cue(Model):
    kind: Literal["text", "photo"] = "text"
    key: str = Field(min_length=1, max_length=500)
    label: str = Field(default="", max_length=500)


class EventInput(Model):
    event_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=200_000)
    role: Literal["user", "assistant", "tool", "system"]
    source: str = Field(min_length=1, max_length=500)
    session_id: str = Field(default="default", min_length=1, max_length=200)
    category: Literal["conversation", "reference", "persona"] = "conversation"
    cues: list[Cue] = Field(default_factory=list, max_length=20)
    occurred_at: str = Field(default_factory=now)

    @field_validator("occurred_at")
    @classmethod
    def valid_time(cls, value: str) -> str:
        return timestamp(value)


class MemoryCandidate(Model):
    content: str = Field(min_length=1, max_length=4000)
    kind: Literal["fact", "preference", "agreement", "growth", "emotion", "observation", "episode"]
    gist: str | None = Field(default=None, min_length=1, max_length=160)
    basis: Literal["user_statement", "assistant_expression", "inference"]
    source_quote: str = Field(min_length=1, max_length=4000)
    confidence: float = Field(default=0.7, ge=0, le=1)
    subject: str = Field(default="", max_length=200)
    fact_key: str | None = Field(default=None, min_length=1, max_length=200)
    valid_at: str | None = None
    related_memory_ids: list[str] = Field(default_factory=list, max_length=20)
    # Emotion is an expression, not a claim about subjective consciousness.
    valence: float | None = Field(default=None, ge=-1, le=1)
    arousal: float | None = Field(default=None, ge=0, le=1)

    @field_validator("valid_at")
    @classmethod
    def valid_time(cls, value: str | None) -> str | None:
        return timestamp(value) if value is not None else None


class Extraction(Model):
    memories: list[MemoryCandidate] = Field(default_factory=list, max_length=30)


class TaskState(Model):
    goal: str = Field(max_length=4000)
    completed: list[str] = Field(default_factory=list, max_length=100)
    pending: list[str] = Field(default_factory=list, max_length=100)
    constraints: list[str] = Field(default_factory=list, max_length=100)
    next_step: str = Field(default="", max_length=4000)

    @field_validator("completed", "pending", "constraints")
    @classmethod
    def bounded_items(cls, items: list[str]) -> list[str]:
        if any(len(item) > 4000 for item in items):
            raise ValueError("Task items cannot exceed 4000 characters")
        return items


class Persona(Model):
    name: str = Field(min_length=1, max_length=200)
    traits: list[str] = Field(max_length=50)
    values: list[str] = Field(max_length=50)
    style: list[str] = Field(max_length=50)
    boundaries: list[str] = Field(max_length=50)

    @field_validator("traits", "values", "style", "boundaries")
    @classmethod
    def bounded_items(cls, items: list[str]) -> list[str]:
        if any(len(item) > 2000 for item in items):
            raise ValueError("Persona items cannot exceed 2000 characters")
        return items


DEFAULT_PERSONA = Persona(
    name="知伴",
    traits=["温和、好奇，有自己的判断", "遇到不确定的事情坦诚说明"],
    values=["尊重用户自主选择", "重视事实、约定和共同经历"],
    style=["用自然、简明的中文交流", "工作时优先清晰准确，代码和数据不加角色语气"],
    boundaries=["不编造共同经历", "不把推测说成事实", "不声称拥有人的主观感受"],
)
