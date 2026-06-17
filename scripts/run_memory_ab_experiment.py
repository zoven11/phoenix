"""Run a Phoenix long-term-memory A/B experiment.

The script runs the same document set twice:

1. without evolution memory
2. with evolution memory and the shared memory pool enabled

It then summarizes accuracy, iterations, failing fields, and memory usage into a
Markdown report. Use ``--summarize-only`` when both workspaces already exist.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACES_ROOT = REPO_ROOT / "local" / "workspaces"
DEFAULT_REPORT = REPO_ROOT / "local" / "reports" / "memory_ab_experiment.md"


@dataclass
class EvaluationMetrics:
    accuracy: float | None = None
    field_average: float | None = None
    doc_count: int | None = None
    error_count: int | None = None
    failing_fields: list[str] | None = None


@dataclass
class WorkspaceMetrics:
    name: str
    workspace: Path
    status: str
    error: str | None
    iterations: int
    duration_sec: float | None
    initial_eval: EvaluationMetrics
    final_eval: EvaluationMetrics
    memory_usage_events: int
    used_memory_ids: list[str]
    memory_records: int
    candidate_records: int
    evidence_records: int


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _filter_usage_rows_for_run(
    rows: list[dict[str, Any]],
    *,
    started_at: datetime | None,
    finished_at: datetime | None,
) -> list[dict[str, Any]]:
    if started_at is None:
        return rows
    filtered: list[dict[str, Any]] = []
    for row in rows:
        created_at = _parse_datetime(row.get("created_at"))
        if created_at is None:
            continue
        if created_at < started_at:
            continue
        if finished_at is not None and created_at > finished_at:
            continue
        filtered.append(row)
    return filtered


def _shared_usage_rows(workspace: Path, *, started_at: datetime | None, finished_at: datetime | None) -> list[dict[str, Any]]:
    category_path = workspace / ".phoenix_memory" / "document_category.json"
    category = _read_json(category_path)
    family = category.get("document_family") or category.get("category")
    topic = category.get("document_topic")
    pool_root = REPO_ROOT / "local" / "memory_pool"
    rows: list[dict[str, Any]] = []
    if topic:
        rows.extend(_read_jsonl(pool_root / "topics" / str(topic) / "usage.jsonl"))
    if family:
        rows.extend(_read_jsonl(pool_root / "families" / str(family) / "usage.jsonl"))
    return _filter_usage_rows_for_run(rows, started_at=started_at, finished_at=finished_at)


def _format_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2%}"


def _evaluation_from_iteration(item: dict[str, Any]) -> EvaluationMetrics | None:
    evaluation = item.get("evaluation")
    if not isinstance(evaluation, dict):
        return None
    field_accuracies = evaluation.get("field_accuracies") or {}
    failing_fields = [
        field
        for field, score in field_accuracies.items()
        if isinstance(score, (int, float)) and score < 1.0
    ]
    return EvaluationMetrics(
        accuracy=evaluation.get("accuracy"),
        field_average=evaluation.get("field_average"),
        doc_count=evaluation.get("doc_count"),
        error_count=evaluation.get("error_count"),
        failing_fields=failing_fields,
    )


def collect_workspace_metrics(name: str, workspace: Path) -> WorkspaceMetrics:
    state_dir = workspace / ".agent_state"
    current = _read_json(state_dir / "current.json")
    started_at = _parse_datetime(current.get("started_at"))
    finished_at = _parse_datetime(current.get("finished_at"))

    evaluations: list[EvaluationMetrics] = []
    iterations_dir = state_dir / "iterations"
    if iterations_dir.exists():
        for path in sorted(iterations_dir.glob("iter_*.json")):
            metrics = _evaluation_from_iteration(_read_json(path))
            if metrics is not None:
                evaluations.append(metrics)

    memory_dir = workspace / ".phoenix_memory"
    usage_rows = _filter_usage_rows_for_run(
        _read_jsonl(memory_dir / "usage.jsonl"),
        started_at=started_at,
        finished_at=finished_at,
    )
    usage_rows.extend(
        _shared_usage_rows(
            workspace,
            started_at=started_at,
            finished_at=finished_at,
        )
    )
    used_memory_ids: list[str] = []
    for row in usage_rows:
        ids = row.get("memory_ids") or []
        if isinstance(ids, list):
            used_memory_ids.extend(str(item) for item in ids)

    return WorkspaceMetrics(
        name=name,
        workspace=workspace,
        status=str(current.get("status") or "unknown"),
        error=current.get("error"),
        iterations=int(current.get("current_iteration") or len(evaluations) or 0),
        duration_sec=current.get("total_run_duration_sec"),
        initial_eval=evaluations[0] if evaluations else EvaluationMetrics(),
        final_eval=evaluations[-1] if evaluations else EvaluationMetrics(),
        memory_usage_events=len(usage_rows),
        used_memory_ids=sorted(set(used_memory_ids)),
        memory_records=len(_read_jsonl(memory_dir / "memories.jsonl")),
        candidate_records=len(_read_jsonl(memory_dir / "candidates.jsonl")),
        evidence_records=len(_read_jsonl(memory_dir / "evidence.jsonl")),
    )


def build_auto_command(args: argparse.Namespace, workspace: Path, *, memory_enabled: bool) -> list[str]:
    command = [
        "uv",
        "run",
        "agentic-extract",
        "auto",
        "--workspace",
        str(workspace),
    ]
    if args.pdfs_dir:
        command.extend(["--pdfs-dir", str(args.pdfs_dir)])
    if args.data_dir:
        command.extend(["--data-dir", str(args.data_dir)])
    if args.source_file:
        command.extend(["--source-file", str(args.source_file)])
    if args.limit is not None:
        command.extend(["--limit", str(args.limit)])
    if args.budget:
        command.extend(["--budget", args.budget])
    if args.max_iterations is not None:
        command.extend(["--max-iterations", str(args.max_iterations)])
    if args.target_accuracy is not None:
        command.extend(["--target-accuracy", str(args.target_accuracy)])
    if args.workspace_mode:
        command.extend(["--workspace-mode", args.workspace_mode])
    if args.message:
        command.extend(["--message", args.message])
    if args.document_category:
        command.extend(["--document-category", args.document_category])
    if args.document_family:
        command.extend(["--document-family", args.document_family])
    if args.document_topic:
        command.extend(["--document-topic", args.document_topic])
    if args.memory_global_dir:
        command.extend(["--memory-global-dir", str(args.memory_global_dir)])
    if args.memory_top_k is not None:
        command.extend(["--memory-top-k", str(args.memory_top_k)])
    if memory_enabled:
        command.append("--memory-enabled")
    else:
        command.append("--no-memory-shared-pool")
    return command


def run_command(command: list[str], *, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + " ".join(command) + "\n\n")
        log.flush()
        process = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        log.write(f"\n\nexit_code={process.returncode}\n")
        return process.returncode


def prepare_workspace(path: Path, *, overwrite: bool) -> None:
    if not path.exists():
        return
    if not overwrite:
        raise SystemExit(
            f"Workspace already exists: {path}\n"
            "Use --overwrite to remove experiment workspaces before running."
        )
    shutil.rmtree(path)


def render_report(
    *,
    args: argparse.Namespace,
    no_memory: WorkspaceMetrics,
    with_memory: WorkspaceMetrics,
    no_memory_exit: int | None,
    with_memory_exit: int | None,
) -> str:
    created_at = datetime.now(timezone.utc).isoformat()
    no_fields = ", ".join(no_memory.final_eval.failing_fields or []) or "-"
    with_fields = ", ".join(with_memory.final_eval.failing_fields or []) or "-"
    accuracy_delta = None
    if no_memory.final_eval.accuracy is not None and with_memory.final_eval.accuracy is not None:
        accuracy_delta = with_memory.final_eval.accuracy - no_memory.final_eval.accuracy

    lines = [
        "# Phoenix 长期记忆 A/B 实验报告",
        "",
        f"- 生成时间: `{created_at}`",
        f"- PDF目录: `{args.pdfs_dir or '-'}`",
        f"- 数据目录: `{args.data_dir or '-'}`",
        f"- Source文件: `{args.source_file or '-'}`",
        f"- 共享经验池: `{args.memory_global_dir or REPO_ROOT / 'local' / 'memory_pool'}`",
        f"- Budget: `{args.budget or '-'}`",
        f"- 最大迭代: `{args.max_iterations if args.max_iterations is not None else '-'}`",
        "",
        "## 结果对比",
        "",
        "| 实验组 | Memory | 退出码 | 状态 | 初始准确率 | 最终准确率 | 准确率提升 | 字段平均 | 迭代数 | 错误文档数 | 失败字段 | 使用经验次数 | 使用经验数 | 生成记忆数 |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|",
        (
            f"| {no_memory.name} | 关闭 | {no_memory_exit if no_memory_exit is not None else '-'} "
            f"| {no_memory.status} | {_format_pct(no_memory.initial_eval.accuracy)} "
            f"| {_format_pct(no_memory.final_eval.accuracy)} | - "
            f"| {_format_pct(no_memory.final_eval.field_average)} | {no_memory.iterations} "
            f"| {no_memory.final_eval.error_count if no_memory.final_eval.error_count is not None else '-'} "
            f"| {no_fields} | {no_memory.memory_usage_events} "
            f"| {len(no_memory.used_memory_ids)} | {no_memory.memory_records} |"
        ),
        (
            f"| {with_memory.name} | 开启 | {with_memory_exit if with_memory_exit is not None else '-'} "
            f"| {with_memory.status} | {_format_pct(with_memory.initial_eval.accuracy)} "
            f"| {_format_pct(with_memory.final_eval.accuracy)} | {_format_pct(accuracy_delta)} "
            f"| {_format_pct(with_memory.final_eval.field_average)} | {with_memory.iterations} "
            f"| {with_memory.final_eval.error_count if with_memory.final_eval.error_count is not None else '-'} "
            f"| {with_fields} | {with_memory.memory_usage_events} "
            f"| {len(with_memory.used_memory_ids)} | {with_memory.memory_records} |"
        ),
        "",
        "## Workspace 明细",
        "",
        f"- 无经验 workspace: `{no_memory.workspace}`",
        f"- 有经验 workspace: `{with_memory.workspace}`",
        f"- 无经验日志: `{no_memory.workspace / '.agent_state' / 'memory_ab_no_memory.log'}`",
        f"- 有经验日志: `{with_memory.workspace / '.agent_state' / 'memory_ab_with_memory.log'}`",
        "",
        "## 经验复用检查",
        "",
        f"- 有经验组 usage 事件数: `{with_memory.memory_usage_events}`",
        f"- 有经验组命中的 memory_ids: `{', '.join(with_memory.used_memory_ids) or '-'}`",
        f"- 有经验组 workspace memories: `{with_memory.memory_records}`",
        f"- 有经验组 candidates: `{with_memory.candidate_records}`",
        f"- 有经验组 evidence: `{with_memory.evidence_records}`",
        "",
        "判断标准：如果有经验组 `usage` 事件数大于 0，说明长期记忆确实被注入过；如果最终准确率更高或达到同等准确率所需迭代更少，说明经验复用对本批样本有效。",
        "",
    ]
    if no_memory.error or with_memory.error:
        lines.extend(
            [
                "## 运行错误",
                "",
                f"- 无经验组错误: `{no_memory.error or '-'}`",
                f"- 有经验组错误: `{with_memory.error or '-'}`",
                "",
            ]
        )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phoenix memory A/B experiment.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--pdfs-dir", type=Path, help="PDF directory used by agentic-extract auto.")
    source.add_argument("--data-dir", type=Path, help="Existing .xdev data directory to import.")
    source.add_argument("--source-file", type=Path, help="Phoenix source file for data import.")
    parser.add_argument("--workspace-prefix", default="memory-ab", help="Workspace name prefix under local/workspaces.")
    parser.add_argument("--no-memory-workspace", type=Path, help="Existing or target workspace for the no-memory group.")
    parser.add_argument("--with-memory-workspace", type=Path, help="Existing or target workspace for the memory group.")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT, help="Markdown report path.")
    parser.add_argument("--budget", default="fast", help="Budget preset passed to agentic-extract auto.")
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--target-accuracy", type=float, default=None)
    parser.add_argument("--workspace-mode", default="default", choices=["default", "incremental_reuse"])
    parser.add_argument("--message", help="Initial message passed to Supervisor.")
    parser.add_argument("--limit", type=int, help="Limit imported documents when supported by the source.")
    parser.add_argument("--document-category")
    parser.add_argument("--document-family")
    parser.add_argument("--document-topic")
    parser.add_argument("--memory-global-dir", type=Path)
    parser.add_argument("--memory-top-k", type=int)
    parser.add_argument("--overwrite", action="store_true", help="Remove experiment workspaces before running.")
    parser.add_argument("--summarize-only", action="store_true", help="Only summarize existing workspaces.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.summarize_only and not (args.pdfs_dir or args.data_dir or args.source_file):
        raise SystemExit("One of --pdfs-dir, --data-dir, or --source-file is required unless --summarize-only is used.")

    no_memory_workspace = args.no_memory_workspace or DEFAULT_WORKSPACES_ROOT / f"{args.workspace_prefix}-no-memory"
    with_memory_workspace = args.with_memory_workspace or DEFAULT_WORKSPACES_ROOT / f"{args.workspace_prefix}-with-memory"
    no_memory_workspace = no_memory_workspace.resolve()
    with_memory_workspace = with_memory_workspace.resolve()

    no_memory_exit: int | None = None
    with_memory_exit: int | None = None
    if not args.summarize_only:
        prepare_workspace(no_memory_workspace, overwrite=args.overwrite)
        prepare_workspace(with_memory_workspace, overwrite=args.overwrite)

        no_command = build_auto_command(args, no_memory_workspace, memory_enabled=False)
        no_memory_exit = run_command(
            no_command,
            log_path=no_memory_workspace / ".agent_state" / "memory_ab_no_memory.log",
        )

        with_command = build_auto_command(args, with_memory_workspace, memory_enabled=True)
        with_memory_exit = run_command(
            with_command,
            log_path=with_memory_workspace / ".agent_state" / "memory_ab_with_memory.log",
        )

    no_memory = collect_workspace_metrics("A", no_memory_workspace)
    with_memory = collect_workspace_metrics("B", with_memory_workspace)
    report = render_report(
        args=args,
        no_memory=no_memory,
        with_memory=with_memory,
        no_memory_exit=no_memory_exit,
        with_memory_exit=with_memory_exit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Wrote report: {args.output}")
    print(f"No-memory final accuracy: {_format_pct(no_memory.final_eval.accuracy)}")
    print(f"With-memory final accuracy: {_format_pct(with_memory.final_eval.accuracy)}")
    print(f"With-memory usage events: {with_memory.memory_usage_events}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
