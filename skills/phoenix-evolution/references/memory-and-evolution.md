# Memory and Evolution

Use this file when converting Phoenix runs into durable knowledge.

## Read Order

1. `.agent_state/current.json`
2. `.agent_state/events.jsonl`
3. `.agent_state/iterations/`
4. `.agent_state/supervisor.json`
5. `.agent_state/dev_agent.json`
6. `.agent_state/business_agent.json`
7. `.agent_state/evolution_notes.md`
8. `.agent_state/run_commands.md`
9. `.agent_state/conversation_summary.md`
10. `xdev run` output
11. `xdev eval` output
12. `business_guide.md`

Prefer native Phoenix logs for facts about `agentic-extract run`. Use Codex-side
notes only for commands, direct edits, and diagnostics that happened outside
`agentic-extract`.

## Failure Taxonomy

- extraction missed a field
- field value is malformed
- schema is wrong
- sample coverage is too narrow
- prompt is too vague
- parsing or OCR is broken
- reuse was attempted on the wrong scene

## What To Preserve

- recurring failure patterns
- stable field definitions
- document family heuristics
- validation rules
- good examples and bad examples
- source classification: `native-agentic`, `codex-side`, or `hybrid`
- run id, iteration id, and final status when available

## Where To Write It

- `business_guide.md`: long-lived business rules and field meanings
- `program.py`: executable extraction logic
- `.agent_state/evolution_notes.md`: append-only reusable lessons
- `.agent_state/run_commands.md`: Codex-side command provenance
- `.agent_state/conversation_summary.md`: readable decision trail

## How To Evolve

Write a new iteration message from the failure summary, not from the raw log.
Keep the message short, specific, and testable.

Before writing the next iteration message, check whether the same failure label
or document pattern already exists in `evolution_notes.md`. Reuse the prior
lesson as a hypothesis, then verify it with `xdev run` and baseline `xdev eval`.
