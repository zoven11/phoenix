"""Runtime facade for isolated long-term evolution memory."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from .category_pool import (
    detect_document_category,
    normalize_category_slug,
    resolve_shared_memory_root,
    write_category_detection,
)
from .evidence import build_iteration_evidence
from .models import EvolutionMemoryRecord, EvolutionMemoryUsage
from .prompt import render_memory_context
from .store import EvolutionMemoryStore
from .summarize import build_field_candidates, build_run_candidate
from .validate import promote_candidate


@dataclass
class MemorySelection:
    memory: EvolutionMemoryRecord
    store: EvolutionMemoryStore
    source_pool: str


class EvolutionMemoryRuntime:
    """Small facade used by runner.py to keep memory integration isolated."""

    def __init__(
        self,
        *,
        enabled: bool,
        run_id: str,
        workspace_store: EvolutionMemoryStore | None,
        family_store: EvolutionMemoryStore | None,
        topic_store: EvolutionMemoryStore | None,
        top_k: int,
        document_category: str | None,
        document_family: str | None,
        document_topic: str | None,
        field_group: str | None,
    ):
        self.enabled = enabled
        self.run_id = run_id
        self.workspace_store = workspace_store
        self.family_store = family_store
        self.topic_store = topic_store
        self.top_k = top_k
        self.document_category = document_category
        self.document_family = document_family
        self.document_topic = document_topic
        self.field_group = field_group
        self._used_memory_refs: list[tuple[EvolutionMemoryStore, list[str]]] = []

    @classmethod
    def from_settings(cls, settings, workspace_path: Path) -> "EvolutionMemoryRuntime":
        enabled = bool(getattr(settings, "memory_enabled", False))
        if not enabled:
            return cls(
                enabled=False,
                run_id=uuid.uuid4().hex,
                workspace_store=None,
                family_store=None,
                topic_store=None,
                top_k=0,
                document_category=None,
                document_family=None,
                document_topic=None,
                field_group=None,
            )

        root_name = getattr(settings, "memory_runtime_dirname", ".phoenix_memory")
        runtime_root = workspace_path / root_name
        workspace_store = EvolutionMemoryStore(runtime_root)
        workspace_store.ensure_initialized()
        detection = detect_document_category(
            workspace_path,
            explicit=getattr(settings, "document_category", None),
            runtime_root=runtime_root,
            explicit_family=getattr(settings, "document_family", None),
            explicit_topic=getattr(settings, "document_topic", None),
        )
        document_category = detection.category
        document_family = detection.document_family or detection.category
        document_topic = detection.document_topic
        field_group = detection.field_group
        write_category_detection(runtime_root, detection)
        family_store = None
        topic_store = None
        if getattr(settings, "memory_shared_pool_enabled", True):
            shared_root = resolve_shared_memory_root(
                workspace_path,
                getattr(settings, "memory_global_dir", None),
            )
            family_slug = normalize_category_slug(document_family)
            topic_slug = normalize_category_slug(document_topic)
            if family_slug:
                family_store = EvolutionMemoryStore(shared_root / "families" / family_slug)
                family_store.ensure_initialized()
            if topic_slug:
                topic_store = EvolutionMemoryStore(shared_root / "topics" / topic_slug)
                topic_store.ensure_initialized()
        return cls(
            enabled=True,
            run_id=uuid.uuid4().hex,
            workspace_store=workspace_store,
            family_store=family_store,
            topic_store=topic_store,
            top_k=max(int(getattr(settings, "memory_top_k", 8)), 0),
            document_category=document_category,
            document_family=document_family,
            document_topic=document_topic,
            field_group=field_group,
        )

    def _iter_candidate_memories(self) -> list[MemorySelection]:
        if not self.enabled or self.workspace_store is None:
            return []
        selections: list[MemorySelection] = []
        for store, source_pool in [
            (self.workspace_store, "workspace"),
            (self.topic_store, "topic"),
            (self.family_store, "family"),
        ]:
            if store is None:
                continue
            for item in store.list_memories():
                if item.status not in {"active", "candidate"}:
                    continue
                if source_pool == "topic" and self.document_topic:
                    if item.document_topic and item.document_topic != self.document_topic:
                        continue
                if source_pool == "family" and self.document_family:
                    if item.document_family and item.document_family != self.document_family:
                        continue
                selections.append(
                    MemorySelection(
                        memory=item.model_copy(update={"source_pool": source_pool}),
                        store=store,
                        source_pool=source_pool,
                    )
                )
        return selections

    def selected_memories(self) -> list[MemorySelection]:
        selections = self._iter_candidate_memories()
        if not selections:
            return []
        unique: list[MemorySelection] = []
        seen: set[tuple[str | None, str | None, str | None, str | None, str | None, str, str]] = set()
        for selection in selections:
            memory = selection.memory
            signature = (
                memory.document_family or memory.document_category,
                memory.document_topic,
                memory.field_group,
                memory.failure_category or memory.category,
                memory.field_name,
                memory.problem_pattern,
                memory.recommended_action,
            )
            if signature in seen:
                continue
            seen.add(signature)
            unique.append(selection)
        source_rank = {"workspace": 0, "topic": 1, "family": 2}
        unique.sort(
            key=lambda item: (
                source_rank.get(item.source_pool, 99),
                item.memory.status != "active",
                -item.memory.quality_score,
                -item.memory.success_count,
                item.memory.title or item.memory.problem_pattern or item.memory.id,
            )
        )
        return unique[: self.top_k]

    def selected_memories_for_fields(self, field_names: list[str] | None) -> list[MemorySelection]:
        """Prefer field-specific memories for the current failing fields, with fallback."""
        normalized = {name.strip() for name in (field_names or []) if name and name.strip()}
        selections = self.selected_memories()
        if not normalized:
            return selections
        field_specific = [
            item for item in selections if item.memory.field_name and item.memory.field_name in normalized
        ]
        generic = [item for item in selections if item not in field_specific]
        return field_specific + generic

    def build_initial_context(self) -> str:
        selections = self.selected_memories()
        if self.enabled and selections:
            self._record_usage_for_selections(selections, iteration=None)
        return render_memory_context([item.memory for item in selections])

    def build_field_context(self, *, field_names: list[str] | None, iteration: int | None) -> str:
        """Render additional field-targeted context after an evaluation exposes failing fields."""
        selections = self.selected_memories_for_fields(field_names)
        if not selections:
            return ""
        focused = [item for item in selections if item.memory.field_name]
        if focused:
            selections = focused + [item for item in selections if not item.memory.field_name]
        selections = selections[: self.top_k]
        if self.enabled and selections:
            self._record_usage_for_selections(selections, iteration=iteration)
        return render_memory_context([item.memory for item in selections])

    def _record_usage_for_selections(
        self,
        selections: list[MemorySelection],
        *,
        iteration: int | None,
    ) -> None:
        grouped: dict[int, tuple[EvolutionMemoryStore, list[str]]] = {}
        for selection in selections:
            key = id(selection.store)
            if key not in grouped:
                grouped[key] = (selection.store, [])
            grouped[key][1].append(selection.memory.id)
        self._used_memory_refs = []
        for store, memory_ids in grouped.values():
            store.append_usage(
                EvolutionMemoryUsage(
                    run_id=self.run_id,
                    iteration=iteration,
                    memory_ids=memory_ids,
                )
            )
            store.record_usage_hits(memory_ids)
            self._used_memory_refs.append((store, memory_ids))

    def record_iteration_evidence(
        self,
        *,
        iteration: int,
        action: str | None,
        summary: str | None,
        error: str | None,
        evaluation,
        git_commit_before: str,
        git_commit_after: str,
    ) -> None:
        if not self.enabled or self.workspace_store is None:
            return
        evidence = build_iteration_evidence(
            run_id=self.run_id,
            iteration=iteration,
            action=action,
            summary=summary,
            error=error,
            evaluation=evaluation,
            git_commit_before=git_commit_before,
            git_commit_after=git_commit_after,
        )
        self.workspace_store.append_evidence(evidence)
        if self.family_store is not None and self.document_family:
            self.family_store.append_evidence(
                evidence.model_copy(
                    update={
                        "id": uuid.uuid4().hex,
                    }
                )
            )
        if self.topic_store is not None and self.document_topic:
            self.topic_store.append_evidence(
                evidence.model_copy(
                    update={
                        "id": uuid.uuid4().hex,
                    }
                )
            )

    def finalize_run(self, *, exit_reason: str, completed: bool) -> None:
        if not self.enabled or self.workspace_store is None:
            return
        evidence = [
            item
            for item in self.workspace_store.list_evidence()
            if item.run_id == self.run_id
        ]
        if evidence:
            if self.family_store is not None and self.document_family:
                for item in evidence:
                    self.family_store.append_evidence(
                        item.model_copy(
                            update={
                                "id": uuid.uuid4().hex,
                            }
                        )
                    )
            if self.topic_store is not None and self.document_topic:
                for item in evidence:
                    self.topic_store.append_evidence(
                        item.model_copy(
                            update={
                                "id": uuid.uuid4().hex,
                            }
                        )
                    )
        candidate = build_run_candidate(
            run_id=self.run_id,
            evidence=evidence,
            exit_reason=exit_reason,
            completed=completed,
            document_category=self.document_category,
            document_family=self.document_family,
            document_topic=self.document_topic,
            field_group=self.field_group,
        )
        if candidate is not None:
            self.workspace_store.append_candidate(candidate)
            if self.family_store is not None and self.document_family:
                self.family_store.append_candidate(
                    candidate.model_copy(
                        update={
                            "id": uuid.uuid4().hex,
                            "scope": "family",
                            "document_category": self.document_category,
                            "document_family": self.document_family,
                            "document_topic": None,
                            "field_group": None,
                        }
                    )
                )
            if self.topic_store is not None and self.document_topic:
                self.topic_store.append_candidate(
                    candidate.model_copy(
                        update={
                            "id": uuid.uuid4().hex,
                            "scope": "topic",
                            "document_category": self.document_category,
                            "document_family": self.document_family,
                            "document_topic": self.document_topic,
                            "field_group": self.field_group,
                        }
                    )
                )
            memory = promote_candidate(candidate)
            if memory is not None:
                self.workspace_store.upsert_memory(memory)
                if self.family_store is not None and self.document_family:
                    family_memory = memory.model_copy(
                        update={
                            "id": uuid.uuid4().hex,
                            "scope": "family",
                            "document_category": self.document_category,
                            "document_family": self.document_family,
                            "document_topic": None,
                            "field_group": None,
                            "source_pool": "family",
                        }
                    )
                    self.family_store.upsert_memory(family_memory)
                if self.topic_store is not None and self.document_topic:
                    topic_memory = memory.model_copy(
                        update={
                            "id": uuid.uuid4().hex,
                            "scope": "topic",
                            "document_category": self.document_category,
                            "document_family": self.document_family,
                            "document_topic": self.document_topic,
                            "field_group": self.field_group,
                            "source_pool": "topic",
                        }
                    )
                    self.topic_store.upsert_memory(topic_memory)
        for candidate in build_field_candidates(
            run_id=self.run_id,
            evidence=evidence,
            document_category=self.document_category,
            document_family=self.document_family,
            document_topic=self.document_topic,
            field_group=self.field_group,
        ):
            self.workspace_store.append_candidate(candidate)
            if self.family_store is not None and self.document_family:
                self.family_store.append_candidate(
                    candidate.model_copy(
                        update={
                            "id": uuid.uuid4().hex,
                            "scope": "family",
                            "document_category": self.document_category,
                            "document_family": self.document_family,
                            "document_topic": None,
                            "field_group": None,
                        }
                    )
                )
            if self.topic_store is not None and self.document_topic:
                self.topic_store.append_candidate(
                    candidate.model_copy(
                        update={
                            "id": uuid.uuid4().hex,
                            "scope": "topic",
                            "document_category": self.document_category,
                            "document_family": self.document_family,
                            "document_topic": self.document_topic,
                            "field_group": self.field_group,
                        }
                    )
                )
            memory = promote_candidate(candidate)
            if memory is None:
                continue
            self.workspace_store.upsert_memory(memory)
            if self.family_store is not None and self.document_family:
                family_memory = memory.model_copy(
                    update={
                        "id": uuid.uuid4().hex,
                        "scope": "family",
                        "document_category": self.document_category,
                        "document_family": self.document_family,
                        "document_topic": None,
                        "field_group": None,
                        "source_pool": "family",
                    }
                )
                self.family_store.upsert_memory(family_memory)
            if self.topic_store is not None and self.document_topic:
                topic_memory = memory.model_copy(
                    update={
                        "id": uuid.uuid4().hex,
                        "scope": "topic",
                        "document_category": self.document_category,
                        "document_family": self.document_family,
                        "document_topic": self.document_topic,
                        "field_group": self.field_group,
                        "source_pool": "topic",
                    }
                )
                self.topic_store.upsert_memory(topic_memory)
        for store, memory_ids in self._used_memory_refs:
            store.record_run_feedback(
                memory_ids=memory_ids,
                completed=completed,
                had_evaluation=any(item.accuracy is not None for item in evidence),
            )
