"""Evidence collection helpers for long-term evolution memory."""

from __future__ import annotations

import uuid

from .models import EvolutionMemoryEvidence


def _failing_fields(evaluation) -> list[str]:
    if evaluation is None:
        return []
    field_accuracies = getattr(evaluation, "field_accuracies", {}) or {}
    return [
        field
        for field, accuracy in field_accuracies.items()
        if accuracy is not None and accuracy < 1.0
    ]


def build_iteration_evidence(
    *,
    run_id: str,
    iteration: int,
    action: str | None,
    summary: str | None,
    error: str | None,
    evaluation,
    git_commit_before: str,
    git_commit_after: str,
) -> EvolutionMemoryEvidence:
    """Create a normalized evidence record from a completed iteration."""
    failing_fields = _failing_fields(evaluation)
    return EvolutionMemoryEvidence(
        id=uuid.uuid4().hex,
        run_id=run_id,
        source="iteration",
        iteration=iteration,
        action=action,
        summary=summary or "",
        error=error,
        accuracy=(evaluation.accuracy if evaluation is not None else None),
        field_average=(evaluation.field_average if evaluation is not None else None),
        doc_count=(evaluation.doc_count if evaluation is not None else None),
        error_count=(evaluation.error_count if evaluation is not None else None),
        error_doc_ids=(evaluation.error_doc_ids if evaluation is not None else []),
        failing_fields=failing_fields,
        failure_category=("field_extraction_failure" if failing_fields else None),
        git_commit_before=git_commit_before,
        git_commit_after=git_commit_after,
    )
