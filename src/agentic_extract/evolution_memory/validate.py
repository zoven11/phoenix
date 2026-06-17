"""Validation rules for promoting candidates into long-term memories."""

from __future__ import annotations

import uuid

from .models import EvolutionMemoryCandidate, EvolutionMemoryRecord


def promote_candidate(candidate: EvolutionMemoryCandidate) -> EvolutionMemoryRecord | None:
    """Promote a candidate into an active memory if it passes basic checks."""
    if not candidate.recommended_action.strip():
        return None
    if not candidate.problem_pattern.strip():
        return None
    if not candidate.evidence_refs and not candidate.source_evidence_ids:
        return None

    return EvolutionMemoryRecord(
        id=uuid.uuid4().hex,
        scope=candidate.scope,
        memory_type=candidate.memory_type,
        status="active",
        title=candidate.title,
        field_name=candidate.field_name,
        category=candidate.category,
        document_category=candidate.document_category,
        document_family=candidate.document_family or candidate.document_category,
        document_topic=candidate.document_topic,
        field_group=candidate.field_group,
        failure_category=candidate.failure_category or candidate.category,
        section_hint=candidate.section_hint,
        position_hint=candidate.position_hint,
        anchor_keywords=list(candidate.anchor_keywords),
        canonical_examples=list(candidate.canonical_examples),
        normalization_rule=candidate.normalization_rule,
        layout_pattern=candidate.layout_pattern,
        problem_pattern=candidate.problem_pattern,
        applicable_conditions=candidate.applicable_conditions,
        recommended_action=candidate.recommended_action,
        forbidden_action=candidate.forbidden_action,
        quality_score=0.6,
        use_count=0,
        success_count=0,
        failure_count=0,
        evidence_refs=list(candidate.evidence_refs),
        source_evidence_ids=list(candidate.source_evidence_ids),
        last_validated_at=candidate.created_at,
    )
