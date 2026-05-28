---
name: phoenix-evolution
description: >
  Evolve Phoenix PDF extraction workflows by reusing prior workspaces, reading
  agent logs, distilling failures into durable memory, and turning evaluation
  feedback into the next agentic-extract iteration. Use when improving an
  existing Phoenix extraction process, recovering from bad runs, or building a
  reusable scene library across document types.
metadata:
  openclaw:
    requires:
      bins:
        - agentic-extract
        - xdev
        - xdev-config
        - ppx
---

# Phoenix Evolution

Use this skill when the goal is not just to run Phoenix, but to make Phoenix
better over time.

## What This Skill Does

1. Reuses existing scenes before starting new work.
2. Reads Phoenix native run logs and evaluation output to find failure patterns.
3. Writes durable notes into workspace memory files.
4. Turns those notes into the next `agentic-extract run` message.
5. Builds a reusable library of document-type playbooks.

## Core Loop

1. Identify the document type and target fields.
2. Check for a reusable workspace or scene.
3. Read existing memory before testing:
   `.agent_state/evolution_notes.md`, `.agent_state/run_commands.md`,
   `.agent_state/conversation_summary.md`, `.agent_state/events.jsonl`, and
   `.agent_state/iterations/`.
4. Run or continue extraction.
5. Inspect `xdev run`, `xdev eval`, and Phoenix native logs.
6. Classify the failure or reuse success.
7. Append the lesson into memory without overwriting prior lessons.
8. Re-run with a sharper message.

## Source Of Truth

Treat Phoenix native logs as the primary factual source for agentic runs:

- `.agent_state/events.jsonl`: complete event stream.
- `.agent_state/iterations/iter_*.json`: per-iteration summaries.
- `.agent_state/supervisor.json`, `dev_agent.json`, `business_agent.json`:
  agent conversation memories.
- `.agent_state/current.json`: pointer to the latest completed run.

Use Codex-side command output as a secondary source when tests, direct patches,
or diagnostics happen outside `agentic-extract`. Preserve those in
`.agent_state/run_commands.md` and `.agent_state/conversation_summary.md`.

Do not claim an experience came from `agentic-extract` unless it is supported
by the native logs. When both native logs and Codex-side notes exist, merge
them into one append-only lesson in `evolution_notes.md`.

For deterministic extraction of native-log facts, prefer running:

```powershell
python <skill>/scripts/extract_native_log_experience.py --workspace <workspace> --output <workspace>/.agent_state/native_experience_extract.md
```

Use the script output as factual substrate, then let the agent compact it into
`evolution_notes.md` or a scene playbook.

## Auto Deposition

After every reuse or generalization test, write a compact lesson record before
the next iteration. The record should preserve the tested PDF, workspace,
extraction output, evidence from the source text, root cause, and the next
`agentic-extract run` message. This turns each failure into a reusable scene
asset instead of a one-off observation.

When `agentic-extract run` was used, generate the lesson from native logs first
and only then add Codex-side observations. When only `xdev` or shell commands
were used, mark the lesson as `codex-side` instead of `native-agentic`.

## Auto Repair Policy

When a Phoenix extraction test fails and the source text contains the missing
field evidence, do not stop after reporting the problem. Continue the loop
automatically:

1. Read the workspace memory, especially `.agent_state/evolution_notes.md`.
2. Classify the failure as parsing, schema, business-rule, reuse, or code logic.
3. Prefer repairing through `agentic-extract run` so Phoenix records the
   iteration in `.agent_state/events.jsonl` and `.agent_state/iterations/`.
4. Directly patch `program.py` only when the user explicitly asks for a manual
   fix, when `agentic-extract` is unavailable, or when a tiny deterministic
   hotfix is needed before a follow-up `agentic-extract run`.
5. Re-test the failing PDF.
6. Run the original labeled evaluation set.
7. Append the repair result back to `evolution_notes.md`.

## Agentic Iteration First

For normal Phoenix evolution, use this order:

1. Read existing memory and native logs for reusable patterns.
2. `xdev run` on the new PDF to expose the concrete failure.
3. Read source evidence and append/update `evolution_notes.md`.
4. Run `agentic-extract run --workspace <workspace> --message '<focused repair request>'`.
5. Watch `.agent_state/events.jsonl` or foreground output until completion.
6. Archive the native run into `evolution_notes.md`.
7. Run `xdev run` on the failing PDF again.
8. Run `xdev eval --workspace <workspace> --data-dir <workspace>/.xdev`.
9. Record command output and final status.

This makes `agentic-extract` the actor that changes the extractor and preserves
the native Phoenix iteration trail. Use `xdev` as the measurement tool, not as
the repair engine.

Ask the user only when the next step would change task scope, require missing
business judgment, use paid/network resources not already implied by the task,
or risk overwriting unrelated work.

## When To Read References

- `references/scene-portfolio.md`: when comparing document types or deciding reuse.
- `references/feedback-loop.md`: when turning errors into a better follow-up prompt.
- `references/memory-and-evolution.md`: when summarizing logs, lessons, and long-term notes.
- `references/auto-deposition.md`: when saving a test result into durable memory.
- `references/native-log-archive.md`: when deriving experience from Phoenix native logs.

## Relationship To Phoenix

This skill complements the base `phoenix` skill. Use `phoenix` for the command
workflow, and use this skill when the task is about reuse, iteration, memory,
or process improvement.
