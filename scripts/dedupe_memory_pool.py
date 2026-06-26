"""Deduplicate Phoenix evolution-memory pool files.

The script only rewrites ``memories.jsonl`` files. It keeps the strongest record
per semantic key and merges evidence/tags from duplicates.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from agentic_extract.evolution_memory.models import EvolutionMemoryRecord


def _semantic_key(memory: EvolutionMemoryRecord) -> tuple[str | None, ...]:
    return (
        memory.scope,
        memory.memory_type,
        memory.document_category,
        memory.document_family,
        memory.document_topic,
        memory.field_group,
        memory.field_name,
        memory.failure_category or memory.category,
    )


def _merge_unique(left: list[str], right: list[str]) -> list[str]:
    merged = list(left)
    seen = set(left)
    for item in right:
        if item in seen:
            continue
        merged.append(item)
        seen.add(item)
    return merged


def _location_score(memory: EvolutionMemoryRecord) -> int:
    score = 0
    score += 1 if memory.section_hint else 0
    score += 1 if memory.position_hint else 0
    score += min(len(memory.anchor_keywords), 5)
    score += min(len(memory.canonical_examples), 3)
    score += 1 if memory.normalization_rule else 0
    score += 1 if memory.layout_pattern else 0
    score += 1 if memory.recommended_action else 0
    score += 1 if memory.forbidden_action else 0
    return score


def _rank(memory: EvolutionMemoryRecord) -> tuple[float, int, int, int, str]:
    return (
        memory.quality_score,
        memory.success_count,
        -memory.failure_count,
        _location_score(memory),
        memory.last_validated_at.isoformat() if memory.last_validated_at else "",
    )


def _merge_into(target: EvolutionMemoryRecord, duplicate: EvolutionMemoryRecord) -> None:
    target.evidence_refs = _merge_unique(target.evidence_refs, duplicate.evidence_refs)
    target.source_evidence_ids = _merge_unique(target.source_evidence_ids, duplicate.source_evidence_ids)
    target.tags = _merge_unique(target.tags, duplicate.tags)
    target.anchor_keywords = _merge_unique(target.anchor_keywords, duplicate.anchor_keywords)
    target.canonical_examples = _merge_unique(target.canonical_examples, duplicate.canonical_examples)
    target.use_count += duplicate.use_count
    target.success_count += duplicate.success_count
    target.failure_count += duplicate.failure_count
    target.quality_score = max(target.quality_score, duplicate.quality_score)
    if duplicate.last_validated_at and (
        target.last_validated_at is None or duplicate.last_validated_at > target.last_validated_at
    ):
        target.last_validated_at = duplicate.last_validated_at

    for field in [
        "section_hint",
        "position_hint",
        "normalization_rule",
        "layout_pattern",
        "problem_pattern",
        "applicable_conditions",
        "recommended_action",
        "forbidden_action",
        "title",
    ]:
        if not getattr(target, field) and getattr(duplicate, field):
            setattr(target, field, getattr(duplicate, field))


def dedupe_file(path: Path, *, dry_run: bool) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    memories = [
        EvolutionMemoryRecord.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    grouped: dict[tuple[str | None, ...], EvolutionMemoryRecord] = {}
    for memory in memories:
        key = _semantic_key(memory)
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = memory
            continue
        if _rank(memory) > _rank(existing):
            _merge_into(memory, existing)
            grouped[key] = memory
        else:
            _merge_into(existing, memory)

    deduped = list(grouped.values())
    deduped.sort(
        key=lambda item: (
            item.scope,
            item.document_family or "",
            item.document_topic or "",
            item.field_group or "",
            item.field_name or "",
            item.title or item.id,
        )
    )
    if not dry_run and len(deduped) != len(memories):
        path.write_text(
            "".join(item.model_dump_json() + "\n" for item in deduped),
            encoding="utf-8",
        )
    return len(memories), len(deduped)


def iter_memory_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(root.glob("**/memories.jsonl"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, help="memory_pool root or a memories.jsonl file")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    total_before = 0
    total_after = 0
    for path in iter_memory_files(args.root):
        before, after = dedupe_file(path, dry_run=args.dry_run)
        total_before += before
        total_after += after
        if before:
            print(f"{path}: {before} -> {after}")
    print(f"total: {total_before} -> {total_after}")


if __name__ == "__main__":
    main()
