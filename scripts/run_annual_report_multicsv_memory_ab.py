"""Run annual-report multi-CSV incremental memory A/B experiment.

This script merges labels from multiple annual-report CSV files by the same
``met_link`` PDF. It intentionally refuses to merge CSVs that do not refer to the
same PDF, because using a half-year/quarter report label for an annual-report PDF
would make evaluation meaningless.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACES_ROOT = REPO_ROOT / "local" / "workspaces"
DEFAULT_REPORT = REPO_ROOT / "local" / "reports" / "annual_report_multicsv_memory_ab.md"

CSV_DEFAULTS = {
    "audit": Path("/home/zhangshumin/projects/phe/datasets/初始定期审计报告意见.csv"),
    "dividend": Path("/home/zhangshumin/projects/phe/datasets/初始分红转增.csv"),
    "capital": Path("/home/zhangshumin/projects/phe/datasets/初始公司股本结构.csv"),
    "shareholders": Path("/home/zhangshumin/projects/phe/datasets/初始股东人数.csv"),
    "financial": Path("/home/zhangshumin/projects/phe/datasets/主要财务指标表.csv"),
}


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")


def normalize_empty(value: Any, *, empty_as: str = "") -> str:
    if pd.isna(value):
        return empty_as
    text = str(value).strip()
    if text.lower() == "nan":
        return empty_as
    return text


def normalize_ratio(value: Any) -> str:
    text = normalize_empty(value, empty_as="0")
    if text in {"", "-", "—", "——", "/", "不适用"}:
        return "0"
    if text.endswith(".0"):
        return text[:-2]
    return text


def to_bool(value: Any) -> bool:
    text = normalize_empty(value)
    return text in {"是", "true", "True", "TRUE", "1", "已审计"}


def split_names(value: Any) -> list[str]:
    text = normalize_empty(value)
    if not text:
        return []
    for sep in ["，", ",", "；", ";", " "]:
        text = text.replace(sep, "、")
    return [part.strip() for part in text.split("、") if part.strip()]


def to_int(value: Any) -> int | None:
    text = normalize_empty(value)
    if not text:
        return None
    try:
        return int(float(text.replace(",", "")))
    except ValueError:
        return None


def load_schema_fields(base_workspace: Path) -> list[str]:
    schema = json.loads((base_workspace / ".xdev" / "schema.json").read_text(encoding="utf-8"))
    return list((schema.get("data") or {}).keys())


def yearly_links(df: pd.DataFrame) -> set[str]:
    yearly = df[df["met_title"].astype(str).str.contains("年度报告", na=False)]
    return set(yearly["met_link"].astype(str))


def build_rows(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, int]]:
    audit = read_csv(args.audit_csv)
    dividend = read_csv(args.dividend_csv)
    capital = read_csv(args.capital_csv)
    shareholders = read_csv(args.shareholders_csv)
    financial = read_csv(args.financial_csv)

    link_sets = {
        "audit": yearly_links(audit),
        "dividend": yearly_links(dividend),
        "capital": yearly_links(capital),
        "shareholders": yearly_links(shareholders),
        "financial": yearly_links(financial),
    }
    common5 = set.intersection(*link_sets.values())
    common4 = set.intersection(link_sets["audit"], link_sets["dividend"], link_sets["capital"], link_sets["shareholders"])

    if args.require_financial and not common5:
        raise SystemExit(
            "No same-PDF intersection across all 5 CSVs. "
            "The financial CSV appears to refer to different PDFs/report periods."
        )

    links = sorted(common5 if args.require_financial else common4)
    if len(links) < args.limit:
        raise SystemExit(f"Only found {len(links)} common docs; requested {args.limit}.")
    links = links[: args.limit]

    def by_link(df: pd.DataFrame) -> pd.DataFrame:
        return df[df["met_link"].astype(str).isin(links)].copy()

    audit_d = by_link(audit).drop_duplicates("met_link").set_index("met_link")
    dividend_d = by_link(dividend).drop_duplicates("met_link").set_index("met_link")
    capital_d = by_link(capital).drop_duplicates("met_link").set_index("met_link")
    shareholders_d = by_link(shareholders).drop_duplicates("met_link").set_index("met_link")
    financial_d = by_link(financial)

    rows: list[dict[str, Any]] = []
    for link in links:
        a = audit_d.loc[link]
        d = dividend_d.loc[link]
        c = capital_d.loc[link]
        s = shareholders_d.loc[link]
        fin_items: list[dict[str, str]] = []
        if args.require_financial:
            for _, item in financial_d[financial_d["met_link"].astype(str) == link].iterrows():
                current = normalize_empty(item.get("原文_本期金额"))
                previous = normalize_empty(item.get("原文_上期金额"))
                if not current or not previous:
                    continue
                fin_items.append(
                    {
                        "项目": normalize_empty(item.get("原文_项目")),
                        "本期金额": current,
                        "上期金额": previous,
                    }
                )
        label = {
            "is_audited": to_bool(a.get("原文_是否经过审计")),
            "domestic_audit_opinion_type": normalize_empty(a.get("原文_境内审计意见类型")),
            "domestic_signing_cpas": split_names(a.get("原文_境内签名注册会计师")),
            "domestic_audit_firm_name": normalize_empty(a.get("原文_境内会计师事务所名称")),
            "总股本": normalize_empty(c.get("原文_总股本")),
            "已流通股份": normalize_empty(c.get("原文_已流通股份")),
            "人民币普通股": normalize_empty(c.get("原文_人民币普通股")),
            "流通受限股份": normalize_empty(c.get("原文_流通受限股份"), empty_as="0"),
            "其他流通受限股份": normalize_empty(c.get("原文_其他流通受限股份"), empty_as="0"),
            "其中：境内自然人持股": normalize_empty(c.get("原文_其中：境内自然人持股"), empty_as="0"),
            "其他内资持股（受限）": normalize_empty(c.get("原文_其他内资持股（受限）"), empty_as="0"),
            "控股股东、实际控制人": normalize_empty(c.get("原文_控股股东、实际控制人"), empty_as="0"),
            "转增比例 (10: X)": normalize_ratio(d.get("原文_转增比例 (10: X)")),
            "送股比例 (10: X)": normalize_ratio(d.get("原文_送股比例 (10: X)")),
            "派息比例[人民币] (10: X)": normalize_ratio(d.get("原文_派息比例[人民币] (10: X)")),
            "A 股户数": to_int(s.get("原文_A 股户数")),
            "股东总户数": to_int(s.get("原文_股东总户数")),
            "主要财务指标": fin_items,
        }
        rows.append(
            {
                "doc_id": normalize_empty(a.get("met_uuid")).replace("-", ""),
                "met_uuid": normalize_empty(a.get("met_uuid")),
                "met_title": normalize_empty(a.get("met_title")),
                "met_link": link,
                "res_sec_code": normalize_empty(a.get("res_sec_code")),
                "label": label,
            }
        )
    stats = {name: len(values) for name, values in link_sets.items()}
    stats["common5"] = len(common5)
    stats["common4"] = len(common4)
    return rows, stats


def prepare_workspace(base_workspace: Path, target_workspace: Path, *, overwrite: bool) -> None:
    if target_workspace.exists():
        if not overwrite:
            raise SystemExit(f"Workspace already exists: {target_workspace}. Use --overwrite.")
        shutil.rmtree(target_workspace)
    shutil.copytree(base_workspace, target_workspace, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.rmtree(target_workspace / ".agent_state", ignore_errors=True)
    (target_workspace / ".agent_state").mkdir(parents=True, exist_ok=True)
    (REPO_ROOT / "local" / "test_outputs" / target_workspace.name).mkdir(parents=True, exist_ok=True)


def download_pdfs(rows: list[dict[str, Any]], workspace: Path) -> Path:
    pdf_dir = workspace / ".agent_state" / "annual_report_multicsv_pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept": "application/pdf,application/octet-stream,*/*",
        "Referer": "https://www.bse.cn/",
    }
    for index, row in enumerate(rows, start=1):
        pdf_path = pdf_dir / f"{row['doc_id']}.pdf"
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            continue
        print(f"[{index}/{len(rows)}] download {row['met_title']}")
        try:
            import requests

            response = requests.get(row["met_link"], headers=headers, timeout=120, allow_redirects=True)
            response.raise_for_status()
            pdf_path.write_bytes(response.content)
        except ImportError:
            request = urllib.request.Request(row["met_link"], headers=headers)
            with urllib.request.urlopen(request, timeout=120) as response:
                pdf_path.write_bytes(response.read())
        if pdf_path.stat().st_size <= 0:
            raise SystemExit(f"Downloaded empty PDF: {pdf_path}")
    return pdf_dir


def stable_log_path(workspace: Path, filename: str) -> Path:
    return REPO_ROOT / "local" / "test_outputs" / workspace.name / filename


def run_logged(command: list[str], *, cwd: Path, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + " ".join(command) + "\n\n")
        log.flush()
        process = subprocess.run(command, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT, text=True)
        log.write(f"\n\nexit_code={process.returncode}\n")
        return process.returncode


def import_pdfs(workspace: Path, pdf_dir: Path) -> int:
    return run_logged(
        [
            "uv",
            "run",
            "xdev",
            "import-data",
            "--add-pdf",
            str(pdf_dir),
            "--data-dir",
            str(workspace / ".xdev"),
            "--force",
        ],
        cwd=REPO_ROOT,
        log_path=stable_log_path(workspace, "01_import.log"),
    )


def write_labels(workspace: Path, rows: list[dict[str, Any]], schema_fields: list[str]) -> None:
    labels_dir = workspace / ".xdev" / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        label = {field: row["label"].get(field) for field in schema_fields}
        (labels_dir / f"{row['doc_id']}.json").write_text(
            json.dumps(label, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


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
        "annual_report",
        "--document-topic",
        "annual_report_universal",
        "--message",
        (
            "这是通用年报多字段增量复用实验。请先复用当前 program.py 对所有已标注文档做正式 xdev eval；"
            "若任一字段失败，再结合字段级经验最小范围修复 program.py。必须保持 schema 字段不变，"
            "旧文档和新增文档都要评估，通过后 done/completed。"
        ),
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
        log_path=stable_log_path(workspace, "02_auto_with_memory.log" if memory_enabled else "02_auto_no_memory.log"),
    )


def run_eval(workspace: Path, suffix: str) -> int:
    return run_logged(
        ["uv", "run", "xdev", "eval", "--data-dir", str(workspace / ".xdev"), "--workspace", str(workspace)],
        cwd=REPO_ROOT,
        log_path=stable_log_path(workspace, f"03_eval_{suffix}.log"),
    )


def summarize(args: argparse.Namespace, rows: list[dict[str, Any]], stats: dict[str, int], no_ws: Path, with_ws: Path) -> None:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def read_current(ws: Path) -> dict[str, Any]:
        p = ws / ".agent_state" / "current.json"
        if not p.exists():
            return {}
        return json.loads(p.read_text(encoding="utf-8"))
    def count_usage(ws: Path) -> int:
        p = ws / ".phoenix_memory" / "usage.jsonl"
        return len(p.read_text(encoding="utf-8", errors="ignore").splitlines()) if p.exists() else 0
    text = "# 年报多 CSV 通用字段 Memory A/B 实验\n\n"
    text += "## 数据交集\n\n"
    for key, value in stats.items():
        text += f"- `{key}`: {value}\n"
    text += "\n说明：当前 5 张表按同一 PDF 链接交集为 0，因此本轮默认使用审计、分红、股本结构、股东人数 4 张同文档年度报告表；`主要财务指标` 暂为空列表，不纳入有效对比。\n\n"
    text += "## 实验设置\n\n"
    text += f"- Base workspace: `{args.base_workspace}`\n"
    text += f"- Limit: {args.limit}\n"
    text += f"- Budget: `{args.budget}`\n"
    text += f"- No-memory workspace: `{no_ws}`\n"
    text += f"- With-memory workspace: `{with_ws}`\n\n"
    text += "## 文档列表\n\n| 序号 | 标题 | 证券代码 | PDF |\n|---:|---|---:|---|\n"
    for i, row in enumerate(rows, 1):
        text += f"| {i} | {row['met_title']} | {row['res_sec_code']} | {row['met_link']} |\n"
    text += "\n## 运行摘要\n\n"
    text += f"- No-memory current: `{json.dumps(read_current(no_ws), ensure_ascii=False)}`\n"
    text += f"- With-memory current: `{json.dumps(read_current(with_ws), ensure_ascii=False)}`\n"
    text += f"- No-memory usage lines: {count_usage(no_ws)}\n"
    text += f"- With-memory usage lines: {count_usage(with_ws)}\n\n"
    text += "## 日志\n\n"
    text += f"- `{stable_log_path(no_ws, '02_auto_no_memory.log')}`\n"
    text += f"- `{stable_log_path(with_ws, '02_auto_with_memory.log')}`\n"
    text += f"- `{stable_log_path(no_ws, '03_eval_no_memory.log')}`\n"
    text += f"- `{stable_log_path(with_ws, '03_eval_with_memory.log')}`\n"
    args.output.write_text(text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run annual-report multi-CSV memory A/B experiment.")
    parser.add_argument("--base-workspace", type=Path, default=DEFAULT_WORKSPACES_ROOT / "annual_report_universal_seed")
    parser.add_argument("--audit-csv", type=Path, default=CSV_DEFAULTS["audit"])
    parser.add_argument("--dividend-csv", type=Path, default=CSV_DEFAULTS["dividend"])
    parser.add_argument("--capital-csv", type=Path, default=CSV_DEFAULTS["capital"])
    parser.add_argument("--shareholders-csv", type=Path, default=CSV_DEFAULTS["shareholders"])
    parser.add_argument("--financial-csv", type=Path, default=CSV_DEFAULTS["financial"])
    parser.add_argument("--require-financial", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--workspace-prefix", default="annual-report-universal-multicsv-10")
    parser.add_argument("--budget", default="full")
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--only", choices=["both", "no-memory", "with-memory"], default="both")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_workspace = args.base_workspace.resolve()
    schema_fields = load_schema_fields(base_workspace)
    rows, stats = build_rows(args)
    no_workspace = DEFAULT_WORKSPACES_ROOT / f"{args.workspace_prefix}-no-memory"
    with_workspace = DEFAULT_WORKSPACES_ROOT / f"{args.workspace_prefix}-with-memory"
    jobs = [
        (no_workspace, False, "no_memory"),
        (with_workspace, True, "with_memory"),
    ]
    if args.only == "no-memory":
        jobs = [jobs[0]]
    elif args.only == "with-memory":
        jobs = [jobs[1]]

    for workspace, memory_enabled, suffix in jobs:
        prepare_workspace(base_workspace, workspace, overwrite=args.overwrite)
        pdf_dir = download_pdfs(rows, workspace)
        if import_pdfs(workspace, pdf_dir) != 0:
            raise SystemExit(f"import-data failed: {workspace}")
        write_labels(workspace, rows, schema_fields)
        auto_exit = run_auto(args, workspace, memory_enabled=memory_enabled)
        if auto_exit != 0:
            raise SystemExit(f"agentic-extract auto failed: {workspace}")
        run_eval(workspace, suffix)
    summarize(args, rows, stats, no_workspace, with_workspace)
    print(args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
