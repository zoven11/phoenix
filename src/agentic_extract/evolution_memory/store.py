"""File-backed storage for long-term evolution memory."""

from __future__ import annotations

import json
from pathlib import Path

from .models import (
    EvolutionMemoryCandidate,
    EvolutionMemoryEvidence,
    EvolutionMemoryRecord,
    EvolutionMemoryUsage,
)


class EvolutionMemoryStore:
    """Persist long-term memories in a runtime-only directory."""

    def __init__(self, root: Path):
        self.root = root
        self.memories_path = root / "memories.jsonl"
        self.candidates_path = root / "candidates.jsonl"
        self.evidence_path = root / "evidence.jsonl"
        self.usage_path = root / "usage.jsonl"
        self.index_path = root / "index.json"

    def ensure_initialized(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for path in [self.memories_path, self.candidates_path, self.evidence_path, self.usage_path]:
            if not path.exists():
                path.write_text("", encoding="utf-8")
        if not self.index_path.exists():
            self.index_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "description": "Long-term evolution memory runtime store",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    def list_memories(self) -> list[EvolutionMemoryRecord]:
        if not self.memories_path.exists():
            return []
        records: list[EvolutionMemoryRecord] = []
        for line in self.memories_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            records.append(EvolutionMemoryRecord.model_validate_json(line))
        return records

    def append_usage(self, usage: EvolutionMemoryUsage) -> None:
        self.ensure_initialized()
        with self.usage_path.open("a", encoding="utf-8") as fh:
            fh.write(usage.model_dump_json())
            fh.write("\n")

    def append_evidence(self, evidence: EvolutionMemoryEvidence) -> None:
        self.ensure_initialized()
        with self.evidence_path.open("a", encoding="utf-8") as fh:
            fh.write(evidence.model_dump_json())
            fh.write("\n")

    def list_evidence(self) -> list[EvolutionMemoryEvidence]:
        if not self.evidence_path.exists():
            return []
        records: list[EvolutionMemoryEvidence] = []
        for line in self.evidence_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            records.append(EvolutionMemoryEvidence.model_validate_json(line))
        return records

    def append_candidate(self, candidate: EvolutionMemoryCandidate) -> None:
        self.ensure_initialized()
        with self.candidates_path.open("a", encoding="utf-8") as fh:
            fh.write(candidate.model_dump_json())
            fh.write("\n")

    def list_candidates(self) -> list[EvolutionMemoryCandidate]:
        if not self.candidates_path.exists():
            return []
        records: list[EvolutionMemoryCandidate] = []
        for line in self.candidates_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            records.append(EvolutionMemoryCandidate.model_validate_json(line))
        return records

    def append_memory(self, memory: EvolutionMemoryRecord) -> None:
        self.ensure_initialized()
        with self.memories_path.open("a", encoding="utf-8") as fh:
            fh.write(memory.model_dump_json())
            fh.write("\n")

    def upsert_memory(self, memory: EvolutionMemoryRecord) -> EvolutionMemoryRecord:
        """Insert a new memory or merge it into a similar existing one."""
        self.ensure_initialized()
        memories = self.list_memories()
        match = self._find_similar_memory(memories, memory)
        if match is None:
            self.append_memory(memory)
            return memory

        match.evidence_refs = _merge_unique(match.evidence_refs, memory.evidence_refs)
        match.source_evidence_ids = _merge_unique(match.source_evidence_ids, memory.source_evidence_ids)
        match.tags = _merge_unique(match.tags, memory.tags)
        match.use_count += memory.use_count
        match.success_count += max(memory.success_count, 1)
        match.failure_count += memory.failure_count
        match.quality_score = min(max(match.quality_score, memory.quality_score) + 0.05, 1.0)
        if memory.last_validated_at is not None:
            match.last_validated_at = memory.last_validated_at
        self._rewrite_memories(memories)
        return match

    def record_usage_hits(self, memory_ids: list[str]) -> None:
        """Increment use counters for memories that were injected into a run."""
        if not memory_ids:
            return
        memories = self.list_memories()
        changed = False
        id_set = set(memory_ids)
        for memory in memories:
            if memory.id in id_set:
                memory.use_count += 1
                changed = True
        if changed:
            self._rewrite_memories(memories)

    def record_run_feedback(
        self,
        *,
        memory_ids: list[str],
        completed: bool,
        had_evaluation: bool,
    ) -> None:
        """Update quality metrics for memories after a run completes."""
        if not memory_ids:
            return
        memories = self.list_memories()
        changed = False
        id_set = set(memory_ids)
        for memory in memories:
            if memory.id not in id_set:
                continue
            changed = True
            if completed:
                memory.success_count += 1
                memory.quality_score = min(memory.quality_score + 0.05, 1.0)
            else:
                memory.failure_count += 1
                delta = 0.03 if had_evaluation else 0.01
                memory.quality_score = max(memory.quality_score - delta, 0.0)

            if memory.failure_count >= 3 and memory.failure_count > memory.success_count:
                memory.status = "suppressed"
            elif memory.success_count >= 2 and memory.quality_score >= 0.6:
                memory.status = "active"

        if changed:
            self._rewrite_memories(memories)

    def _rewrite_memories(self, memories: list[EvolutionMemoryRecord]) -> None:
        self.ensure_initialized()
        with self.memories_path.open("w", encoding="utf-8") as fh:
            for memory in memories:
                fh.write(memory.model_dump_json())
                fh.write("\n")

    @staticmethod
    def _find_similar_memory(
        memories: list[EvolutionMemoryRecord],
        candidate: EvolutionMemoryRecord,
    ) -> EvolutionMemoryRecord | None:
        for memory in memories:
            if (
                memory.scope == candidate.scope
                and memory.memory_type == candidate.memory_type
                and memory.document_category == candidate.document_category
                and memory.document_family == candidate.document_family
                and memory.document_topic == candidate.document_topic
                and memory.field_group == candidate.field_group
                and (memory.failure_category or memory.category) == (candidate.failure_category or candidate.category)
                and memory.field_name == candidate.field_name
                and memory.problem_pattern == candidate.problem_pattern
                and memory.recommended_action == candidate.recommended_action
            ):
                return memory
        return None


def _merge_unique(left: list[str], right: list[str]) -> list[str]:
    merged = list(left)
    seen = set(left)
    for item in right:
        if item in seen:
            continue
        merged.append(item)
        seen.add(item)
    return merged
