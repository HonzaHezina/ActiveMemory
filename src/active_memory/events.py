"""Versioned public event contract (schema_version 1).

Events are rows of the operational ``audit`` table that carry a structured ``event`` document; there is
no second journal. This module owns the vocabulary and validation, ``journal.py`` the storage.
Events never copy message text or quotes: they reference sources and candidates by identifier.
"""

import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = 1
PRODUCER = "active-memory"
SYSTEM_ACTOR = "active-memory"

EVENT_TYPES = (
    "candidate.created",
    "candidate.evidence_added",
    "candidate.confirmed",
    "candidate.rejected",
    "candidate.snapshot",
    "context.assembled",
    "source.deleted",
)
ID = r"^[\w.:@/+=-]{1,200}$"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Actor(Strict):
    kind: Literal["human", "system", "model"]
    identifier: str = Field(pattern=ID)
    # How the identity was established. A bearer token authenticates a client; it does not prove that
    # a person physically pressed a button.
    assurance: Literal["bearer_token", "internal", "none"] = "none"


class Subject(Strict):
    kind: Literal["node", "link", "source", "memory_scope"]
    identifier: str = Field(pattern=ID)


class Ref(Strict):
    kind: Literal["source", "node", "link"]
    id: str = Field(pattern=ID)


class Origin(Strict):
    """Who/what produced one contribution to a candidate. Unknown stays null."""

    kind: Literal[
        "client_supplied_extraction", "llm_extraction", "similarity", "judge", "temporal", "manual"
    ]
    supplied_by_client: str | None = None
    model: str | None = None
    provider: str | None = None
    score: float | None = None


class CandidateCreated(Strict):
    candidate_kind: str
    origin: Origin
    evidence_count: int = Field(ge=0)


class EvidenceAdded(Strict):
    origin: Origin
    evidence_count: int = Field(ge=0)


class Decision(Strict):
    pass


class Snapshot(Strict):
    basis: Literal["baseline_snapshot", "reconciliation"]
    note: str


class ContextAssembled(Strict):
    requester: str
    items_returned: int = Field(ge=0)
    max_chars_requested: int = Field(ge=1)
    chars_used: int = Field(ge=0)
    truncated: bool
    include_candidates: bool
    as_of: str | None = None
    target_assistant: None = None  # no authenticated source for it exists yet


class SourceDeleted(Strict):
    derived_stores_cleaned: list[str]


DATA_MODELS = {
    "candidate.created": CandidateCreated,
    "candidate.evidence_added": EvidenceAdded,
    "candidate.confirmed": Decision,
    "candidate.rejected": Decision,
    "candidate.snapshot": Snapshot,
    "context.assembled": ContextAssembled,
    "source.deleted": SourceDeleted,
}
STATES = {"candidate", "confirmed", "rejected", "live", "deleted"}


class EventBody(Strict):
    """What a producer supplies; ids, sequence and recorded_at are assigned on write."""

    type: Literal[EVENT_TYPES]
    occurred_at: datetime | None
    actor: Actor
    subject: Subject
    previous_state: str | None = None
    new_state: str | None = None
    provenance: list[Ref] = Field(default_factory=list, max_length=200)
    correlation_id: str = Field(pattern=ID)
    data: dict

    @field_validator("occurred_at")
    @classmethod
    def aware(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("occurred_at requires timezone")
        return value.astimezone(timezone.utc) if value else None

    @field_validator("previous_state", "new_state")
    @classmethod
    def known_state(cls, value):
        if value is not None and value not in STATES:
            raise ValueError("unknown state")
        return value


def build(
    type,
    *,
    actor,
    subject,
    correlation_id,
    data,
    previous_state=None,
    new_state=None,
    provenance=(),
    occurred_at="now",
):
    """Validate a new event body and return its storable dict."""
    when = datetime.now(timezone.utc) if occurred_at == "now" else occurred_at
    body = EventBody(
        type=type,
        occurred_at=when,
        actor=actor,
        subject=subject,
        previous_state=previous_state,
        new_state=new_state,
        provenance=list(provenance),
        correlation_id=correlation_id,
        data=DATA_MODELS[type].model_validate(data).model_dump(mode="json"),
    )
    return body.model_dump(mode="json")


def iso(epoch):
    return (
        datetime.fromtimestamp(epoch, timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def safe_correlation(value):
    return value if value and re.fullmatch(ID, value) else None
