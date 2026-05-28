#!/usr/bin/env python3
"""汇总 Phoenix 运行的耗时与 token 消耗。

读取 <workspace>/.agent_state/current.json 与 iterations/iter_*.json，
输出每轮迭代和总计的耗时和 token 数。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from datetime import datetime


def parse_iso(ts: str | None):
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize Phoenix run stats")
    parser.add_argument("--workspace", required=True, help="workspace 目录路径")
    parser.add_argument("--output", help="可选，将报告写入该文件而非 stdout")
    args = parser.parse_args()

    state_dir = os.path.join(args.workspace, ".agent_state")
    cur_path = os.path.join(state_dir, "current.json")
    iter_glob = os.path.join(state_dir, "iterations", "iter_*.json")

    if not os.path.isfile(cur_path):
        print(f"current.json 不存在: {cur_path}")
        return 1

    cur = json.load(open(cur_path))
    iters = [json.load(open(f)) for f in sorted(glob.glob(iter_glob))]

    lines: list[str] = []
    lines.append("# Phoenix 运行统计")
    lines.append("")
    lines.append(f"- Workspace: `{args.workspace}`")
    lines.append(f"- 状态: `{cur.get('status')}`")
    lines.append(f"- 开始: {cur.get('started_at')}")
    lines.append(f"- 完成: {cur.get('finished_at')}")

    t0 = parse_iso(cur.get("started_at"))
    t1 = parse_iso(cur.get("finished_at"))
    if t0 and t1:
        total = (t1 - t0).total_seconds()
        lines.append(f"- 总耗时: {total:.1f}s ({total/60:.2f} min)")
    lines.append("")
    lines.append("## 每轮迭代")
    lines.append("")
    lines.append("| 轮 | 动作 | 耗时(s) | total tokens | input | output | cached_in | reasoning |")
    lines.append("|---|---|---|---|---|---|---|---|")

    sum_dur = sum_tok = sum_in = sum_out = sum_cache = sum_rea = 0
    for it in iters:
        n = it.get("iteration")
        act = (it.get("supervisor_decision") or {}).get("action", "?")
        dur = it.get("duration_sec", 0)
        tu = it.get("token_usage") or {}
        t = tu.get("total_tokens", 0)
        i = tu.get("input_tokens", 0)
        o = tu.get("output_tokens", 0)
        c = tu.get("cached_input_tokens", 0)
        r = tu.get("reasoning_output_tokens", 0)
        sum_dur += dur; sum_tok += t; sum_in += i; sum_out += o
        sum_cache += c; sum_rea += r
        lines.append(f"| {n} | {act} | {dur:.1f} | {t} | {i} | {o} | {c} | {r} |")

    lines.append(f"| **合计** | | **{sum_dur:.1f}** | **{sum_tok}** | **{sum_in}** | **{sum_out}** | **{sum_cache}** | **{sum_rea}** |")

    report = "\n".join(lines) + "\n"
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(report)
        print(f"写入: {args.output}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
