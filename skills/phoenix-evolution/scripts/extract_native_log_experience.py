#!/usr/bin/env python
"""Extract reusable Phoenix experience from native agentic logs.

This script reads a Phoenix workspace's `.agent_state` directory and produces a
compact Markdown archive based on native `agentic-extract` evidence. It does not
ask an LLM to summarize raw logs; it first extracts factual candidates:

- current run status
- run ids found in events.jsonl
- per-iteration decisions and evaluation results
- key event counts and final run events
- optional Codex-side supplement file presence

Use the generated Markdown as the factual substrate for `evolution_notes.md`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


KEY_EVENT_TYPES = {
    "run_started",
    "run_completed",
    "supervisor_decided",
    "step_started",
    "step_completed",
    "iteration_started",
    "iteration_completed",
    "phase_started",
    "phase_completed",
    "agent_call_started",
    "agent_call_completed",
}


@dataclass
class EventSummary:
    run_ids: list[str]
    final_events: list[dict[str, Any]]
    event_counts: Counter
    action_counts: Counter
    iteration_events: dict[int, list[dict[str, Any]]]
    errors: list[dict[str, Any]]


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    with path.open("r", encoding="utf-8-sig", errors="replace") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                events.append(
                    {
                        "type": "json_decode_error",
                        "line_no": line_no,
                        "error": str(exc),
                    }
                )
    return events


def summarize_events(events: list[dict[str, Any]]) -> EventSummary:
    run_ids: list[str] = []
    run_id_seen = set()
    final_events: list[dict[str, Any]] = []
    event_counts: Counter = Counter()
    action_counts: Counter = Counter()
    iteration_events: dict[int, list[dict[str, Any]]] = defaultdict(list)
    errors: list[dict[str, Any]] = []

    for event in events:
        event_type = event.get("type") or "(unknown)"
        event_counts[event_type] += 1

        run_id = event.get("run_id")
        if run_id and run_id not in run_id_seen:
            run_id_seen.add(run_id)
            run_ids.append(run_id)

        data = event.get("data")
        if isinstance(data, dict) and data.get("action"):
            action_counts[str(data["action"])] += 1

        iteration = event.get("iteration")
        if isinstance(iteration, int) and (
            event_type in KEY_EVENT_TYPES or event_type == "agent_message"
        ):
            iteration_events[iteration].append(event)

        status = event.get("status")
        message = str(event.get("message") or "")
        if status == "failed" or event_type.endswith("error") or "error" in message.lower():
            errors.append(event)

        if event_type in {"run_completed", "phase_completed"}:
            final_events.append(event)

    return EventSummary(
        run_ids=run_ids,
        final_events=final_events[-5:],
        event_counts=event_counts,
        action_counts=action_counts,
        iteration_events=dict(iteration_events),
        errors=errors[-10:],
    )


def load_iterations(iterations_dir: Path) -> list[dict[str, Any]]:
    if not iterations_dir.exists():
        return []
    iterations: list[dict[str, Any]] = []
    for path in sorted(iterations_dir.glob("iter_*.json")):
        try:
            item = read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            item = {"iteration_file": path.name, "error": str(exc)}
        item["_file"] = path.name
        iterations.append(item)
    return iterations


def text_value(value: Any, limit: int = 500) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    text = " ".join(text.split())
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def format_eval(evaluation: Any) -> list[str]:
    if not isinstance(evaluation, dict):
        return []
    lines = []
    accuracy = evaluation.get("accuracy")
    field_average = evaluation.get("field_average")
    doc_count = evaluation.get("doc_count")
    error_count = evaluation.get("error_count")
    if accuracy is not None:
        lines.append(f"  - Accuracy: {float(accuracy) * 100:.2f}%")
    if field_average is not None:
        lines.append(f"  - Field average: {float(field_average) * 100:.2f}%")
    if doc_count is not None:
        lines.append(f"  - Document count: {doc_count}")
    if error_count is not None:
        lines.append(f"  - Error count: {error_count}")
    field_accuracies = evaluation.get("field_accuracies")
    if isinstance(field_accuracies, dict) and field_accuracies:
        lines.append("  - Field accuracies:")
        for field, value in field_accuracies.items():
            try:
                pct = f"{float(value) * 100:.2f}%"
            except (TypeError, ValueError):
                pct = str(value)
            lines.append(f"    - {field}: {pct}")
    return lines


def infer_reusable_lessons(iterations: list[dict[str, Any]]) -> list[str]:
    lessons: list[str] = []
    seen = set()

    for item in iterations:
        decision = item.get("supervisor_decision")
        if isinstance(decision, dict):
            task_text = text_value(decision.get("task"), limit=900)
            reasoning_text = text_value(decision.get("reasoning"), limit=900)
            combined = f"{task_text} {reasoning_text}"
            for marker in [
                "召开的日期时间",
                "召开地点",
                "现场会议召开时间",
                "股东大会届次",
                "会议地点",
                "heading",
                "next-line",
                "regex",
            ]:
                if marker in combined and marker not in seen:
                    seen.add(marker)
                    lessons.append(f"- Preserve support for pattern: `{marker}`.")

        evaluation = item.get("evaluation")
        if isinstance(evaluation, dict) and evaluation.get("accuracy") == 1.0:
            key = "baseline-eval-100"
            if key not in seen:
                seen.add(key)
                lessons.append(
                    "- After repair, run baseline `xdev eval` and require 100% on existing labeled samples."
                )

        before = item.get("git_commit_before")
        after = item.get("git_commit_after")
        if before and after and before != after:
            key = "version-boundary"
            if key not in seen:
                seen.add(key)
                lessons.append(
                    "- Record git before/after commits for each native repair when available."
                )

    if not lessons:
        lessons.append("- No reusable pattern was inferred automatically; review native decisions manually.")
    return lessons


def render_markdown(workspace: Path) -> str:
    agent_state = workspace / ".agent_state"
    current_path = agent_state / "current.json"
    events_path = agent_state / "events.jsonl"
    iterations_dir = agent_state / "iterations"

    current = read_json(current_path) if current_path.exists() else {}
    events = load_jsonl(events_path)
    event_summary = summarize_events(events)
    iterations = load_iterations(iterations_dir)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []
    lines.append(f"# Phoenix Native Experience Extract")
    lines.append("")
    lines.append(f"- Generated at: {now}")
    lines.append(f"- Workspace: `{workspace}`")
    lines.append(f"- Source class: `native-agentic`")
    lines.append("")

    lines.append("## Current Run")
    if current:
        lines.append(f"- Status: `{current.get('status', 'unknown')}`")
        lines.append(f"- Current iteration: `{current.get('current_iteration', 'unknown')}`")
        lines.append(f"- Started at: `{current.get('started_at', '')}`")
        lines.append(f"- Finished at: `{current.get('finished_at', '')}`")
        lines.append(f"- Error: `{current.get('error', None)}`")
    else:
        lines.append("- No `.agent_state/current.json` found.")
    lines.append("")

    lines.append("## Event Stream")
    if event_summary.run_ids:
        lines.append("- Run ids:")
        for run_id in event_summary.run_ids[-10:]:
            lines.append(f"  - `{run_id}`")
    else:
        lines.append("- No run ids found.")
    lines.append("- Event counts:")
    for event_type, count in event_summary.event_counts.most_common(12):
        lines.append(f"  - `{event_type}`: {count}")
    if event_summary.action_counts:
        lines.append("- Supervisor action counts from event data:")
        for action, count in event_summary.action_counts.most_common():
            lines.append(f"  - `{action}`: {count}")
    lines.append("")

    lines.append("## Iteration Facts")
    if not iterations:
        lines.append("- No iteration JSON files found.")
    for item in iterations:
        iteration = item.get("iteration", item.get("_file", "?"))
        lines.append(f"### Iteration {iteration}")
        lines.append(f"- File: `{item.get('_file', '')}`")
        lines.append(f"- Summary: {text_value(item.get('summary'), limit=700)}")
        lines.append(f"- Error: `{item.get('error', None)}`")
        decision = item.get("supervisor_decision")
        if isinstance(decision, dict):
            lines.append(f"- Supervisor action: `{decision.get('action', '')}`")
            lines.append(f"- Supervisor reasoning: {text_value(decision.get('reasoning'), limit=900)}")
            lines.append(f"- Supervisor task: {text_value(decision.get('task'), limit=900)}")
        before = item.get("git_commit_before")
        after = item.get("git_commit_after")
        if before or after:
            lines.append(f"- Git before: `{before}`")
            lines.append(f"- Git after: `{after}`")
        eval_lines = format_eval(item.get("evaluation"))
        if eval_lines:
            lines.append("- Evaluation:")
            lines.extend(eval_lines)
        output = text_value(item.get("agent_output"), limit=900)
        if output:
            lines.append(f"- Agent output excerpt: {output}")
        lines.append("")

    lines.append("## Final Native Events")
    if event_summary.final_events:
        for event in event_summary.final_events:
            event_type = event.get("type")
            status = event.get("status")
            iteration = event.get("iteration")
            message = text_value(event.get("message"), limit=700)
            lines.append(f"- `{event_type}` status=`{status}` iteration=`{iteration}` message={message}")
    else:
        lines.append("- No final events found.")
    lines.append("")

    lines.append("## Errors")
    if event_summary.errors:
        for event in event_summary.errors:
            lines.append(
                f"- type=`{event.get('type')}` status=`{event.get('status')}` message={text_value(event.get('message'), limit=700)}"
            )
    else:
        lines.append("- No native error events detected.")
    lines.append("")

    lines.append("## Reusable Lesson Candidates")
    lines.extend(infer_reusable_lessons(iterations))
    lines.append("")

    lines.append("## Next Reuse Instruction")
    lines.append("- Read this extract before testing a similar workspace or PDF.")
    lines.append("- Treat lessons as hypotheses; verify with `xdev run` on the new PDF.")
    lines.append("- After any repair, run baseline `xdev eval --data-dir <workspace>/.xdev`.")
    lines.append("- Archive the next native run from `events.jsonl` and `iterations/` before adding Codex-side notes.")
    lines.append("")

    codex_files = [
        agent_state / "run_commands.md",
        agent_state / "conversation_summary.md",
        agent_state / "evolution_notes.md",
    ]
    existing_codex_files = [p.name for p in codex_files if p.exists()]
    if existing_codex_files:
        lines.append("## Codex-Side Supplements Present")
        for name in existing_codex_files:
            lines.append(f"- `{name}`")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Extract reusable experience from Phoenix native agentic logs."
    )
    parser.add_argument(
        "--workspace",
        required=True,
        help="Phoenix workspace path containing .agent_state.",
    )
    parser.add_argument(
        "--output",
        help="Write Markdown extract to this path. Defaults to stdout.",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to --output instead of overwriting it.",
    )
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    if not (workspace / ".agent_state").exists():
        raise SystemExit(f"No .agent_state directory found under {workspace}")

    markdown = render_markdown(workspace)
    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if args.append else "w"
        try:
            with output_path.open(mode, encoding="utf-8", newline="\n") as f:
                if args.append and output_path.stat().st_size > 0:
                    f.write("\n\n")
                f.write(markdown)
                f.write("\n")
        except PermissionError as exc:
            raise SystemExit(
                f"Permission denied writing {output_path}. "
                "Print to stdout without --output, or choose another writable path."
            ) from exc
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
