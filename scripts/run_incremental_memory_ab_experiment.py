"""Run incremental memory A/B from an existing Phoenix workspace.

This is the Phoenix Studio style experiment:

1. copy an existing initialized workspace as the base
2. add new labeled PDF samples from a CSV
3. first reuse existing program.py through ``agentic-extract auto`` in
   ``incremental_reuse`` mode
4. compare memory-off and memory-on runs

Labels are constrained to the base workspace schema. Extra CSV fields are
ignored, so the experiment does not accidentally change the task definition.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACES_ROOT = REPO_ROOT / "local" / "workspaces"
DEFAULT_REPORT = REPO_ROOT / "local" / "reports" / "incremental_memory_ab_experiment.md"

FIELD_ALIASES = {
    "股东大会届次次数": "股东大会届次",
    "是否经过审计": "is_audited",
    "境内审计意见类型": "domestic_audit_opinion_type",
    "境内签名注册会计师": "domestic_signing_cpas",
    "境内会计师事务所名称": "domestic_audit_firm_name",
}


def normalize_field_name(column: str) -> str | None:
    if not column.startswith("原文_"):
        return None
    field = column.removeprefix("原文_")
    return FIELD_ALIASES.get(field, field)


def load_schema_fields(base_workspace: Path) -> list[str]:
    schema_path = base_workspace / ".xdev" / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    data = schema.get("data") or {}
    return list(data.keys())


def convert_label_value(field: str, value: str):
    value = (value or "").strip()
    if field == "is_audited":
        if value in {"是", "true", "True", "TRUE", "1", "已审计"}:
            return True
        if value in {"否", "false", "False", "FALSE", "0", "未审计"}:
            return False
        return False
    if field == "domestic_signing_cpas":
        if not value:
            return []
        normalized = value.replace("，", "、").replace(",", "、").replace("；", "、").replace(";", "、")
        return [item.strip() for item in normalized.split("、") if item.strip()]
    return value


def read_csv_rows(csv_file: Path, *, limit: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with csv_file.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("met_uuid") and row.get("met_link"):
                rows.append(row)
            if len(rows) >= limit:
                break
    if len(rows) < limit:
        raise SystemExit(f"Only found {len(rows)} usable rows in {csv_file}; requested {limit}.")
    return rows


def prepare_workspace(base_workspace: Path, target_workspace: Path, *, overwrite: bool) -> None:
    if target_workspace.exists():
        if not overwrite:
            raise SystemExit(f"Workspace already exists: {target_workspace}. Use --overwrite.")
        shutil.rmtree(target_workspace)
    shutil.copytree(base_workspace, target_workspace)
    shutil.rmtree(target_workspace / ".agent_state", ignore_errors=True)


def download_incremental_pdfs(rows: list[dict[str, str]], target_dir: Path) -> Path:
    pdf_dir = target_dir / ".agent_state" / "csv_incremental_pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows, start=1):
        doc_id = row["met_uuid"].strip()
        url = row["met_link"].strip()
        pdf_path = pdf_dir / f"{doc_id}.pdf"
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            continue
        print(f"[{index}/{len(rows)}] download {doc_id}")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            ),
            "Accept": "application/pdf,application/octet-stream,*/*",
            "Referer": "https://www.bse.cn/",
        }
        try:
            import requests

            response = requests.get(url, headers=headers, timeout=120, allow_redirects=True)
            response.raise_for_status()
            pdf_path.write_bytes(response.content)
        except ImportError:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=120) as response:
                pdf_path.write_bytes(response.read())
        if pdf_path.stat().st_size <= 0:
            raise SystemExit(f"Downloaded empty PDF: {pdf_path}")
    return pdf_dir


def import_pdfs(workspace: Path, pdf_dir: Path) -> int:
    command = [
        "uv",
        "run",
        "xdev",
        "import-data",
        "--add-pdf",
        str(pdf_dir),
        "--data-dir",
        str(workspace / ".xdev"),
        "--force",
    ]
    return run_logged(command, cwd=REPO_ROOT, log_path=workspace / ".agent_state" / "incremental_ab_import.log")


def write_labels(workspace: Path, rows: list[dict[str, str]], schema_fields: list[str]) -> None:
    labels_dir = workspace / ".xdev" / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        raw: dict[str, str] = {}
        for column, value in row.items():
            field = normalize_field_name(column)
            if field:
                raw[field] = value or ""
        label = {field: convert_label_value(field, raw.get(field, "")) for field in schema_fields}
        (labels_dir / f"{row['met_uuid'].strip()}.json").write_text(
            json.dumps(label, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def run_logged(command: list[str], *, cwd: Path, log_path: Path) -> int:
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


def run_auto(args: argparse.Namespace, workspace: Path, *, memory_enabled: bool) -> int:
    command = [
        "uv",
        "run",
        "agentic-extract",
        "auto",
        "--workspace",
        str(workspace),
        "--workspace-mode",
        "incremental_reuse",
        "--budget",
        args.budget,
        "--reset",
        "--document-family",
        args.document_family,
        "--document-topic",
        args.document_topic,
    ]
    if args.max_iterations is not None:
        command.extend(["--max-iterations", str(args.max_iterations)])
    if memory_enabled:
        command.append("--memory-enabled")
    else:
        command.append("--no-memory-shared-pool")
    return run_logged(
        command,
        cwd=REPO_ROOT,
        log_path=workspace / ".agent_state" / ("incremental_ab_with_memory.log" if memory_enabled else "incremental_ab_no_memory.log"),
    )


def summarize_with_existing_script(args: argparse.Namespace, no_workspace: Path, with_workspace: Path) -> int:
    command = [
        "uv",
        "run",
        "python",
        "scripts/run_memory_ab_experiment.py",
        "--summarize-only",
        "--no-memory-workspace",
        str(no_workspace),
        "--with-memory-workspace",
        str(with_workspace),
        "--output",
        str(args.output),
    ]
    return subprocess.run(command, cwd=str(REPO_ROOT)).returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run incremental memory A/B from an existing workspace.")
    parser.add_argument("--base-workspace", type=Path, required=True)
    parser.add_argument("--csv-file", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--workspace-prefix", default="incremental-memory-ab")
    parser.add_argument("--budget", default="full")
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--document-family", default="shareholder_meeting_notice")
    parser.add_argument("--document-topic", default="shareholder_meeting_notice")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_workspace = args.base_workspace.resolve()
    schema_fields = load_schema_fields(base_workspace)
    rows = read_csv_rows(args.csv_file.resolve(), limit=args.limit)

    no_workspace = DEFAULT_WORKSPACES_ROOT / f"{args.workspace_prefix}-no-memory"
    with_workspace = DEFAULT_WORKSPACES_ROOT / f"{args.workspace_prefix}-with-memory"
    for workspace, memory_enabled in [(no_workspace, False), (with_workspace, True)]:
        prepare_workspace(base_workspace, workspace, overwrite=args.overwrite)
        pdf_dir = download_incremental_pdfs(rows, workspace)
        import_exit = import_pdfs(workspace, pdf_dir)
        if import_exit != 0:
            raise SystemExit(f"import-data failed for {workspace}; see incremental_ab_import.log")
        write_labels(workspace, rows, schema_fields)
        run_auto(args, workspace, memory_enabled=memory_enabled)

    summarize_with_existing_script(args, no_workspace, with_workspace)
    print(f"Base workspace: {base_workspace}")
    print(f"Schema fields: {len(schema_fields)} ({', '.join(schema_fields)})")
    print(f"Added CSV docs: {', '.join(row['met_uuid'] for row in rows)}")
    print(f"Report: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
