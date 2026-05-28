# Auto Deposition

Use this workflow after every Phoenix reuse test, generalization test, failed
`xdev run`, or failed `xdev eval`.

## What To Save

Create or append a compact note under the tested workspace, preferably:

```text
<workspace>/.agent_state/evolution_notes.md
```

Each note must state its source class:

- `native-agentic`: derived from Phoenix `agentic-extract` native logs.
- `codex-side`: derived from Codex-run shell commands, `xdev`, or direct edits.
- `hybrid`: combines a native run with Codex-side follow-up.

Also preserve operational logs when the agent performs local tests or direct
repairs outside `agentic-extract`:

```text
<workspace>/.agent_state/run_commands.md
<workspace>/.agent_state/conversation_summary.md
```

If `.agent_state/` is not appropriate for the project, use:

```text
<workspace>/evolution_notes.md
```

## Note Template

```markdown
## <YYYY-MM-DD HH:mm> <scene-name>

- Workspace: <workspace path>
- Source PDF: <pdf path or doc id>
- Command: <xdev/agentic-extract command>
- Expected fields: <field list>
- Actual output:

```json
{}
```

- Evidence from source text:
  - <short source snippet or page/section>
- Diagnosis:
  - <why the current program failed>
- Reuse decision:
  - full reuse | partial reuse | schema-only reuse | no reuse
- Next iteration message:
  - <specific agentic-extract run --message text>
```

## Failure Labels

Use one or more labels:

- `format-gap`: same scene, new wording or layout.
- `regex-gap`: source text exists but the rule misses it.
- `schema-gap`: requested field is missing or poorly defined.
- `source-gap`: PDF/OCR/text extraction is missing the evidence.
- `reuse-mismatch`: copied scene is not actually close enough.
- `evaluation-gap`: no label exists to measure the new case.

## How To Turn A Test Into A Lesson

1. Check whether this came from native Phoenix logs, Codex-side commands, or both.
2. If native logs exist, read `events.jsonl` and `iterations/` first.
3. Save the command and output.
4. Quote only the minimum source evidence needed to prove the field exists.
5. State whether the failure is in source parsing, business rule, schema, or code.
6. Write one specific next message for `agentic-extract run`.
7. If the case is useful for future reuse, add it to the scene portfolio.

## Automatic Repair Rule

If the evidence proves that the source text contains the missing fields, the
agent should continue into repair without waiting for a separate user prompt.

Default order:

1. Search existing `evolution_notes.md` for similar labels or source patterns.
2. Verify any claimed native lesson against `events.jsonl` or `iterations/`.
3. Apply the known repair pattern if one exists.
4. Run `agentic-extract run` with a focused message that cites the evidence,
   failure labels, expected behavior, and regression requirement.
5. Watch the Phoenix event stream until the run completes.
6. Archive the native run result from `events.jsonl` and `iterations/`.
7. Run the failed sample again with `xdev run`.
8. Run the baseline labeled evaluation with `xdev eval`.
9. Append the result, including whether the repair passed or failed.
10. If the repair used `xdev run`, `xdev eval`, shell commands, or direct file
   edits instead of `agentic-extract run`, append those commands to
   `run_commands.md` and summarize the human-agent decision trail in
   `conversation_summary.md`.

Stop and ask only if the failure needs new business definitions, a different
schema, destructive workspace changes, or network/model spending that was not
already part of the requested task.

## `agentic-extract` Versus `xdev`

- `agentic-extract run`: the repair and iteration engine. It can inspect the
  workspace, revise `program.py`, make decisions, and write native Phoenix
  runtime logs under `.agent_state/`.
- `xdev run`: a single-document measurement command. It runs the current
  `program.py` on one PDF or DocJSON and prints the output. It does not iterate.
- `xdev eval`: a labeled-set measurement command. It evaluates the current
  `program.py` against labels. It does not repair the extractor.

Use `xdev run/eval` to find and verify failures. Use `agentic-extract run` to
perform the intelligent repair loop and preserve Phoenix-native history.

## For Generalization Tests

When an old workspace succeeds on its original labels but fails on a new PDF,
classify the result as a generalization failure. Preserve both facts:

- baseline evaluation result on the original workspace
- new PDF extraction result and missing fields

This prevents confusing "the program is broken" with "the program is too narrow."
