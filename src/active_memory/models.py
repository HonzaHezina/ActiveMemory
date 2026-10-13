from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utcnow():
    return datetime.now(timezone.utc)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Kind(StrEnum):
    THEME = "Theme"
    THOUGHT = "Thought"
    FACT = "Fact"
    QUESTION = "Question"
    GOAL = "Goal"
    DECISION = "Decision"


class Relation(StrEnum):
    ABOUT = "ABOUT"
    SUPPORTS = "SUPPORTS"
    REFINES = "REFINES"
    CONTRADICTS = "CONTRADICTS"
    SUPERSEDES = "SUPERSEDES"
    ALIAS_OF = "ALIAS_OF"


class Item(Strict):
    kind: Kind
    label: str = Field(min_length=1, max_length=180)
    summary: str = Field(min_length=1, max_length=2000)
    quote: str = Field(min_length=1, max_length=4000)
    themes: list[Annotated[str, Field(min_length=1, max_length=180)]] = Field(
        default_factory=list, max_length=8
    )
    confidence: float = Field(default=0.5, ge=0, le=1)
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    @field_validator("label", "summary")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("label/summary must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def validity(self):
        for value in (self.valid_from, self.valid_to):
            if value and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("validity timestamps require timezone")
        if self.valid_from and self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from (exclusive end)")
        return self


class Extraction(Strict):
    items: list[Item] = Field(default_factory=list, max_length=24)


class Message(Strict):
    source_system: str = Field(min_length=1, max_length=80, pattern=r"^[\w.-]+$")
    conversation_id: str = Field(min_length=1, max_length=200)
    message_id: str = Field(min_length=1, max_length=200)
    role: Literal["user", "assistant", "tool", "system"]
    content: str = Field(min_length=1, max_length=50000)
    occurred_at: datetime
    extraction: Extraction | None = None

    @field_validator("content")
    @classmethod
    def preserve_raw_content(cls, value):
        if not value.strip():
            raise ValueError("content must not be blank")
        return value

    @field_validator("occurred_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at requires timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def verify_quotes(self):
        for item in self.extraction.items if self.extraction else []:
            if item.quote not in self.content:
                raise ValueError("every quote must be an exact substring of content")
        return self


class Query(Strict):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=12, ge=1, le=50)
    include_candidates: bool = False
    as_of: datetime | None = None
    max_chars: int = Field(default=8000, ge=100, le=32000)

    @field_validator("as_of")
    @classmethod
    def timezone_required(cls, value):
        if value and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("as_of requires timezone")
        return value


class Review(Strict):
    status: Literal["confirmed", "rejected"]


class LinkInput(Strict):
    source_id: str
    target_id: str
    relation: Relation
    episode_id: str
    quote: str = Field(min_length=1, max_length=4000)


class Verdict(Strict):
    """Judge answer for two ideas A and B; quotes must come from the evidence it was shown."""

    relation: Literal["SAME", "SUPPORTS", "REFINES", "CONTRADICTS", "SUPERSEDES", "UNRELATED"]
    direction: Literal["a_to_b", "b_to_a"] = "a_to_b"
    reason: str = Field(min_length=1, max_length=600)
    quote_a: str = Field(default="", max_length=4000)
    quote_b: str = Field(default="", max_length=4000)
