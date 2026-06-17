"""Workspace data preparation helpers for high-level auto entrypoints."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from xdev.api import get_manifest
from xdev.import_data import (
    import_from_data_dir,
    import_from_pdfs,
    import_from_set_id,
    import_from_source,
    sync_pdfs,
)
from xdev.models import DataSourceDataDir, DataSourcePdfs, DataSourceSetId

from .types import (
    PrepareSourceConfigFile,
    PrepareSourceDataDir,
    PrepareSourceExisting,
    PrepareSourcePdfDir,
    PrepareSourceSetId,
    PrepareSpec,
)
from .workspace import ensure_workspace_ready, workspace_has_runnable_data


@dataclass(frozen=True)
class PrepareDecision:
    action: str
    reason: str
    details: dict | None = None


@dataclass(frozen=True)
class PdfSyncPreview:
    added: list[str]
    removed: list[str]
    modified: list[str]
    unchanged: list[str]

    @property
    def total_changes(self) -> int:
        return len(self.added) + len(self.removed) + len(self.modified)


def resolve_prepare_spec(prepare: PrepareSpec | None) -> PrepareSpec:
    return prepare or PrepareSpec()


def inspect_prepare_decision(
    workspace: str | Path,
    prepare: PrepareSpec | None = None,
    *,
    allow_normalize: bool = True,
) -> PrepareDecision:
    workspace_path = Path(workspace).resolve()
    spec = resolve_prepare_spec(prepare)
    has_data = workspace_has_runnable_data(workspace_path, allow_normalize=allow_normalize)

    if isinstance(spec.source, PrepareSourceExisting):
        if has_data:
            return PrepareDecision(action="reuse", reason="workspace 已存在可运行数据")
        return PrepareDecision(action="error", reason="workspace 缺少可运行数据，且未提供数据来源")

    if not has_data:
        return PrepareDecision(action="bootstrap", reason="workspace 缺少可运行数据，需要 bootstrap")

    if _prepare_source_matches_manifest(workspace_path, spec):
        sync_preview = _preview_same_source_pdf_sync(workspace_path, spec)
        if sync_preview is not None and sync_preview.total_changes > 0:
            return PrepareDecision(
                action="sync",
                reason="传入 PDF 目录与现有 manifest 同源，但检测到新增或变更 PDF，需先同步数据层",
                details={
                    "added": sync_preview.added,
                    "removed": sync_preview.removed,
                    "modified": sync_preview.modified,
                    "unchanged": sync_preview.unchanged,
                    "total_changes": sync_preview.total_changes,
                },
            )
        return PrepareDecision(action="reuse", reason="传入数据来源与现有 manifest 同源，跳过 bootstrap")

    return PrepareDecision(action="error", reason="workspace 已存在数据，但传入数据来源不同或无法证明同源")


def prepare_workspace_data(workspace: str | Path, prepare: PrepareSpec | None = None) -> PrepareDecision:
    workspace_path = Path(workspace).resolve()
    spec = resolve_prepare_spec(prepare)
    decision = inspect_prepare_decision(workspace_path, spec, allow_normalize=True)
    if decision.action == "error":
        raise ValueError(decision.reason)
    if decision.action == "reuse":
        ensure_workspace_ready(workspace_path, allow_normalize=True)
        return decision
    if decision.action == "sync":
        source = spec.source
        if not isinstance(source, PrepareSourcePdfDir):  # pragma: no cover - defensive
            raise ValueError("sync 模式仅支持 pdf-dir 数据源")
        sync_result = sync_pdfs(source.pdfs_dir, workspace_path / ".xdev")
        ensure_workspace_ready(workspace_path, allow_normalize=True)
        return PrepareDecision(
            action="sync",
            reason=decision.reason,
            details={
                "added": sync_result.added,
                "removed": sync_result.removed,
                "modified": sync_result.modified,
                "unchanged": sync_result.unchanged,
                "total_changes": sync_result.total_changes,
            },
        )

    xdev_dir = workspace_path / ".xdev"
    source = spec.source
    if isinstance(source, PrepareSourceSetId):
        import_from_set_id(
            source.set_id,
            source.base_url,
            xdev_dir,
            std_ids=source.std_ids,
            limit=source.limit,
        )
    elif isinstance(source, PrepareSourcePdfDir):
        import_from_pdfs(source.pdfs_dir, xdev_dir)
    elif isinstance(source, PrepareSourceDataDir):
        import_from_data_dir(source.data_dir, xdev_dir)
    elif isinstance(source, PrepareSourceConfigFile):
        import_from_source(source.source_file, xdev_dir)
    else:  # pragma: no cover - defensive
        raise ValueError(f"未知 prepare source: {source}")

    ensure_workspace_ready(workspace_path, allow_normalize=True)
    return decision


def _prepare_source_matches_manifest(workspace_path: Path, prepare: PrepareSpec) -> bool:
    manifest = get_manifest(workspace_path / ".xdev")
    if manifest is None:
        return False

    source = prepare.source
    manifest_source = manifest.source

    if isinstance(source, PrepareSourceSetId) and isinstance(manifest_source, DataSourceSetId):
        return (
            manifest_source.set_id == source.set_id
            and manifest_source.base_url == source.base_url
            and (manifest_source.std_ids or None) == (source.std_ids or None)
        )

    if isinstance(source, PrepareSourcePdfDir) and isinstance(manifest_source, DataSourcePdfs):
        return Path(manifest_source.pdf_dir).resolve() == Path(source.pdfs_dir).resolve()

    if isinstance(source, PrepareSourceDataDir) and isinstance(manifest_source, DataSourceDataDir):
        return Path(manifest_source.path).resolve() == Path(source.data_dir).resolve()

    if isinstance(source, PrepareSourceConfigFile):
        return False

    return isinstance(source, PrepareSourceExisting)


def _preview_same_source_pdf_sync(
    workspace_path: Path,
    prepare: PrepareSpec,
) -> PdfSyncPreview | None:
    if not prepare.sync_on_same_source:
        return None

    source = prepare.source
    if not isinstance(source, PrepareSourcePdfDir):
        return None

    manifest = get_manifest(workspace_path / ".xdev")
    if manifest is None or not isinstance(manifest.source, DataSourcePdfs):
        return None

    source_dir = Path(source.pdfs_dir)
    if not source_dir.exists():
        return None

    xdev_dir = workspace_path / ".xdev"
    source_pdf_map = {p.stem: p for p in source_dir.glob("*.pdf")}
    target_pdf_dir = xdev_dir / "data" / "pdf"
    target_doc_ids = {p.stem for p in target_pdf_dir.glob("*.pdf")} if target_pdf_dir.exists() else set()

    added: list[str] = []
    removed: list[str] = []
    modified: list[str] = []
    unchanged: list[str] = []

    for doc_id, src_path in source_pdf_map.items():
        target_pdf = target_pdf_dir / f"{doc_id}.pdf"
        if doc_id not in target_doc_ids:
            added.append(doc_id)
            continue
        if not target_pdf.exists():
            modified.append(doc_id)
            continue
        if _compute_file_hash(src_path) != _compute_file_hash(target_pdf):
            modified.append(doc_id)
        else:
            unchanged.append(doc_id)

    for doc_id in target_doc_ids:
        if doc_id not in source_pdf_map:
            removed.append(doc_id)

    return PdfSyncPreview(
        added=sorted(added),
        removed=sorted(removed),
        modified=sorted(modified),
        unchanged=sorted(unchanged),
    )


def _compute_file_hash(path: Path) -> str:
    md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            md5.update(chunk)
    return md5.hexdigest()
