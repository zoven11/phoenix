"""Data models for long-term evolution memory."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


MemoryScope = Literal["global", "workspace", "category", "family", "topic", "field"]
MemoryType = Literal["observation", "strategy", "constraint", "error_pattern"]
MemoryStatus = Literal["candidate", "active", "suppressed", "retired"]
EvidenceSource = Literal["iteration", "evaluation", "finalize"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EvolutionMemoryRecord(BaseModel):
    """A validated long-term memory record."""

    id: str
    scope: MemoryScope = "workspace"
    memory_type: MemoryType = "strategy"
    status: MemoryStatus = "active"
    title: str = ""
    field_name: str | None = None
    category: str | None = None
    document_category: str | None = None
    document_family: str | None = None
    document_topic: str | None = None
    field_group: str | None = None
    failure_category: str | None = None
    section_hint: str | None = None
    position_hint: str | None = None
    anchor_keywords: list[str] = Field(default_factory=list)
    canonical_examples: list[str] = Field(default_factory=list)
    normalization_rule: str | None = None
    layout_pattern: str | None = None
    problem_pattern: str = ""
    applicable_conditions: str = ""
    recommended_action: str = ""
    forbidden_action: str = ""
    quality_score: float = 0.5
    use_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    evidence_refs: list[str] = Field(default_factory=list)
    source_evidence_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source_pool: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    last_validated_at: datetime | None = None


class EvolutionMemoryUsage(BaseModel):
    """A record of a memory set injected into a run."""

    run_id: str
    iteration: int | None = None
    memory_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class EvolutionMemoryEvidence(BaseModel):
    """Raw evidence collected from a run, kept separate from validated memories."""

    id: str
    run_id: str
    source: EvidenceSource = "iteration"
    iteration: int | None = None
    action: str | None = None
    summary: str = ""
    error: str | None = None
    accuracy: float | None = None
    field_average: float | None = None
    doc_count: int | None = None
    error_count: int | None = None
    error_doc_ids: list[str] = Field(default_factory=list)
    failing_fields: list[str] = Field(default_factory=list)
    failure_category: str | None = None
    git_commit_before: str = ""
    git_commit_after: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class EvolutionMemoryCandidate(BaseModel):
    """A proposed memory distilled from run evidence."""

    id: str
    run_id: str
    title: str = ""
    scope: MemoryScope = "workspace"
    memory_type: MemoryType = "strategy"
    field_name: str | None = None
    category: str | None = None
    document_category: str | None = None
    document_family: str | None = None
    document_topic: str | None = None
    field_group: str | None = None
    failure_category: str | None = None
    section_hint: str | None = None
    position_hint: str | None = None
    anchor_keywords: list[str] = Field(default_factory=list)
    canonical_examples: list[str] = Field(default_factory=list)
    normalization_rule: str | None = None
    layout_pattern: str | None = None
    problem_pattern: str = ""
    applicable_conditions: str = ""
    recommended_action: str = ""
    forbidden_action: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    source_evidence_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
