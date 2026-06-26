"""Persist final extraction results for completed agentic-extract runs."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExtractResultSaveSummary:
    """Summary for saving final extraction results."""

    output_dir: Path
    total_count: int
    success_count: int
    failed: dict[str, str] = field(default_factory=dict)


def _label_doc_ids(data_dir: Path) -> list[str]:
    labels_dir = data_dir / "labels"
    if not labels_dir.exists():
        return []
    return sorted(path.stem for path in labels_dir.glob("*.json") if path.is_file())


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_extract_results_for_labels(workspace: Path | str) -> ExtractResultSaveSummary:
    """Run current ``program.py`` for every labeled document and save results.

    Results are written next to ``.xdev/labels`` using the same per-document file
    naming convention:

    ``.xdev/extract_result/<doc_id>.json``
    """

    workspace_path = Path(workspace).expanduser().resolve()
    data_dir = workspace_path / ".xdev"
    output_dir = data_dir / "extract_result"
    doc_ids = _label_doc_ids(data_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    failed: dict[str, str] = {}
    success_count = 0

    # Import lazily so normal runner startup does not pay xdev/code-executor cost.
    from xdev.evaluation import run_single_extraction

    for doc_id in doc_ids:
        try:
            result = run_single_extraction(doc_id, data_dir=data_dir, workspace=workspace_path)
        except Exception as exc:  # pragma: no cover - exercised by integration/real runs
            failed[doc_id] = str(exc)
            logger.warning("保存提取结果失败 doc_id=%s: %s", doc_id, exc)
            continue
        _write_json(output_dir / f"{doc_id}.json", result)
        success_count += 1

    summary = ExtractResultSaveSummary(
        output_dir=output_dir,
        total_count=len(doc_ids),
        success_count=success_count,
        failed=failed,
    )
    _write_json(
        output_dir / "_summary.json",
        {
            "total_count": summary.total_count,
            "success_count": summary.success_count,
            "failed": summary.failed,
        },
    )
    return summary
