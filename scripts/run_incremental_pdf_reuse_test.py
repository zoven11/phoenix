"""Run a pure-PDF incremental reuse test from an existing Phoenix workspace.

This script is for the Phoenix Studio style flow where a document family already
has a trained workspace/program and users upload more raw PDFs. Raw PDFs do not
have labels, so the report focuses on:

- whether PDFs were imported into the existing data layer
- whether the existing program.py can extract the new PDFs
- whether the workspace already has local/shared memory available for future
  repair steps

It does not fabricate labels or compute accuracy for unlabeled PDFs.
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
DEFAULT_REPORT = REPO_ROOT / "local" / "reports" / "incremental_pdf_reuse_test.md"


@dataclass
class IncrementResult:
    count: int
    workspace: Path
    doc_ids: list[str]
    import_exit: int
    run_results: dict[str, dict[str, Any] | None]
    run_exit_codes: dict[str, int]
    local_memory_count: int
    local_usage_count: int
    family_memory_count: int
    topic_memory_count: int


def _read_jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _load_document_category(workspace: Path) -> dict[str, Any]:
    path = workspace / ".phoenix_memory" / "document_category.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _memory_pool_counts(workspace: Path) -> tuple[int, int]:
    detection = _load_document_category(workspace)
    family = detection.get("document_family") or detection.get("category")
    topic = detection.get("document_topic")
    pool_root = REPO_ROOT / "local" / "memory_pool"
    family_count = _read_jsonl_count(pool_root / "families" / str(family) / "memories.jsonl") if family else 0
    topic_count = _read_jsonl_count(pool_root / "topics" / str(topic) / "memories.jsonl") if topic else 0
    return family_count, topic_count


def _run_command(command: list[str], *, cwd: Path, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + " ".join(command) + "\n\n")
        log.flush()
        process = subprocess.run(
            command,
            cwd=str(cwd),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        log.write(f"\n\nexit_code={process.returncode}\n")
        return process.returncode


def _extract_result_json(output: str) -> dict[str, Any] | None:
    marker = "提取结果:"
    start = output.find(marker)
    if start >= 0:
        output = output[start + len(marker) :]
    brace = output.find("{")
    if brace < 0:
        return None
    candidate = output[brace:].strip()
    end = candidate.rfind("}")
    if end < 0:
        return None
    try:
        return json.loads(candidate[: end + 1])
    except json.JSONDecodeError:
        return None


def _run_xdev_run(workspace: Path, doc_id: str) -> tuple[int, dict[str, Any] | None]:
    command = [
        "uv",
        "run",
        "xdev",
        "run",
        doc_id,
        "--data-dir",
        str(workspace / ".xdev"),
        "--workspace",
        str(workspace),
    ]
    try:
        process = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = process.stdout + process.stderr
        returncode = process.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        output = stdout + stderr + "\n<xdev run timed out after 120s>\n"
        returncode = 124
    log_path = workspace / ".agent_state" / "incremental_pdf_runs" / f"{doc_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("$ " + " ".join(command) + "\n\n" + output, encoding="utf-8")
    return returncode, _extract_result_json(output)


def _copy_selected_pdfs(pdfs: list[Path], target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for pdf in pdfs:
        shutil.copy2(pdf, target_dir / pdf.name)


def _base_doc_ids(base_workspace: Path) -> set[str]:
    pdf_dir = base_workspace / ".xdev" / "data" / "pdf"
    return {path.stem for path in pdf_dir.glob("*.pdf")}


def _select_incremental_pdfs(base_workspace: Path, pdfs_dir: Path, count: int) -> list[Path]:
    existing = _base_doc_ids(base_workspace)
    candidates = [path for path in sorted(pdfs_dir.glob("*.pdf")) if path.stem not in existing]
    return candidates[:count]


def _prepare_workspace(base_workspace: Path, target_workspace: Path, *, overwrite: bool) -> None:
    if target_workspace.exists():
        if not overwrite:
            raise SystemExit(f"Workspace already exists: {target_workspace}. Use --overwrite.")
        shutil.rmtree(target_workspace)
    shutil.copytree(base_workspace, target_workspace)


def run_increment(
    *,
    base_workspace: Path,
    pdfs_dir: Path,
    target_workspace: Path,
    count: int,
    overwrite: bool,
) -> IncrementResult:
    selected = _select_incremental_pdfs(base_workspace, pdfs_dir, count)
    if len(selected) < count:
        raise SystemExit(f"Only found {len(selected)} new PDFs outside the base workspace; requested {count}.")

    _prepare_workspace(base_workspace, target_workspace, overwrite=overwrite)
    add_dir = target_workspace / ".agent_state" / "incremental_pdf_input" / f"{count}_pdfs"
    _copy_selected_pdfs(selected, add_dir)

    import_command = [
        "uv",
        "run",
        "xdev",
        "import-data",
        "--add-pdf",
        str(add_dir),
        "--data-dir",
        str(target_workspace / ".xdev"),
        "--force",
    ]
    import_exit = _run_command(
        import_command,
        cwd=REPO_ROOT,
        log_path=target_workspace / ".agent_state" / "incremental_pdf_import.log",
    )

    run_results: dict[str, dict[str, Any] | None] = {}
    run_exit_codes: dict[str, int] = {}
    for pdf in selected:
        exit_code, result = _run_xdev_run(target_workspace, pdf.stem)
        run_exit_codes[pdf.stem] = exit_code
        run_results[pdf.stem] = result

    family_count, topic_count = _memory_pool_counts(target_workspace)
    return IncrementResult(
        count=count,
        workspace=target_workspace,
        doc_ids=[pdf.stem for pdf in selected],
        import_exit=import_exit,
        run_results=run_results,
        run_exit_codes=run_exit_codes,
        local_memory_count=_read_jsonl_count(target_workspace / ".phoenix_memory" / "memories.jsonl"),
        local_usage_count=_read_jsonl_count(target_workspace / ".phoenix_memory" / "usage.jsonl"),
        family_memory_count=family_count,
        topic_memory_count=topic_count,
    )


def _result_summary(result: dict[str, Any] | None) -> str:
    if not result:
        return "无结果"
    if "success" in result and result.get("success") is False:
        return "提取失败"
    data = result.get("data") if isinstance(result.get("data"), dict) else result
    non_empty = [key for key, value in data.items() if value not in (None, "", [], {})]
    return f"{len(non_empty)} 个非空字段: {', '.join(non_empty[:8])}"


def render_report(args: argparse.Namespace, results: list[IncrementResult]) -> str:
    lines = [
        "# Phoenix 纯 PDF 增量复用测试报告",
        "",
        f"- 生成时间: `{datetime.now(timezone.utc).isoformat()}`",
        f"- 基底 workspace: `{args.base_workspace}`",
        f"- PDF目录: `{args.pdfs_dir}`",
        "",
        "说明：本测试只使用纯 PDF，不补 label，因此不计算新增文档准确率。准确率需要标准答案或 Phoenix Studio 已确认结果作为 label。",
        "",
        "## 递增结果",
        "",
        "| 新增PDF数 | workspace | import退出码 | xdev run成功数 | 本地记忆数 | 本地usage数 | family记忆数 | topic记忆数 | 新增文档 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in results:
        success_count = sum(1 for code in item.run_exit_codes.values() if code == 0)
        lines.append(
            f"| {item.count} | `{item.workspace}` | {item.import_exit} | {success_count}/{len(item.doc_ids)} "
            f"| {item.local_memory_count} | {item.local_usage_count} "
            f"| {item.family_memory_count} | {item.topic_memory_count} "
            f"| {', '.join(item.doc_ids)} |"
        )

    lines.extend(["", "## 单文档提取摘要", ""])
    for item in results:
        lines.append(f"### 新增 {item.count} 份 PDF")
        lines.append("")
        for doc_id in item.doc_ids:
            lines.append(f"- `{doc_id}`: exit={item.run_exit_codes[doc_id]}, {_result_summary(item.run_results[doc_id])}")
        lines.append("")

    lines.extend(
        [
            "## 结论口径",
            "",
            "- `xdev run成功数` 说明旧 workspace 的 `program.py` 是否能直接跑新增 PDF。",
            "- `family/topic记忆数` 说明共享经验池是否存在可复用经验。",
            "- `本地usage数` 只会在 agentic-extract 运行时增加；单纯 `xdev run` 不会注入 prompt，因此不会新增 usage。",
            "- 如果要对新增 PDF 计算准确率，需要把 Phoenix Studio 已确认的提取结果写成 label 后再跑 `xdev eval` 或 A/B 实验。",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pure-PDF incremental reuse tests.")
    parser.add_argument("--base-workspace", type=Path, required=True)
    parser.add_argument("--pdfs-dir", type=Path, required=True)
    parser.add_argument("--increments", default="1,2,3", help="Comma-separated PDF counts, e.g. 1,2,3,5.")
    parser.add_argument("--workspace-prefix", default="shareholder-notice-pdf-increment")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_workspace = args.base_workspace.resolve()
    pdfs_dir = args.pdfs_dir.resolve()
    increments = [int(part.strip()) for part in args.increments.split(",") if part.strip()]
    results: list[IncrementResult] = []
    for count in increments:
        target_workspace = DEFAULT_WORKSPACES_ROOT / f"{args.workspace_prefix}-{count}pdf"
        results.append(
            run_increment(
                base_workspace=base_workspace,
                pdfs_dir=pdfs_dir,
                target_workspace=target_workspace,
                count=count,
                overwrite=args.overwrite,
            )
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_report(args, results), encoding="utf-8")
    print(f"Wrote report: {args.output}")
    for item in results:
        success_count = sum(1 for code in item.run_exit_codes.values() if code == 0)
        print(f"+{item.count} PDFs: xdev run {success_count}/{len(item.doc_ids)} succeeded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
