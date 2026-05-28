# Native Log Archive

Use this reference when generating reusable experience from a Phoenix
`agentic-extract run`.

## Goal

Convert the raw Phoenix run trail into append-only lessons that can guide the
next reuse test or repair run.

## Native Log Locations

Read these files under the tested workspace:

```text
.agent_state/current.json
.agent_state/events.jsonl
.agent_state/iterations/iter_*.json
.agent_state/supervisor.json
.agent_state/dev_agent.json
.agent_state/business_agent.json
```

Meaning:

- `events.jsonl`: primary event stream. Use it to prove what happened.
- `iterations/`: compact per-iteration decisions and outcomes.
- `supervisor.json`: why the supervisor chose evaluate, call_dev, or done.
- `dev_agent.json`: what code changes the dev agent attempted.
- `business_agent.json`: schema, guide, label, and business-rule decisions.
- `current.json`: latest completed run pointer.

## Codex-Side Supplement Logs

When Codex runs commands or patches files outside `agentic-extract`, preserve
those in:

```text
.agent_state/run_commands.md
.agent_state/conversation_summary.md
```

These are secondary evidence. Use them to explain external tests, direct
patches, model/API failures, or manual diagnostics that do not appear in
`events.jsonl`.

## Archive Procedure

1. Identify the run id and final status from `events.jsonl`.
2. Read the related `iterations/iter_*.json` files.
3. Extract only factual events:
   - user request
   - supervisor decision
   - dev/business/evaluator action
   - file changed
   - evaluation result
   - failure message
4. Classify the lesson:
   - `native-agentic`: supported by `agentic-extract` native logs.
   - `codex-side`: produced by xdev, shell commands, or direct Codex edits.
   - `hybrid`: native run plus Codex-side follow-up.
5. Append a compact lesson to `.agent_state/evolution_notes.md`.
6. Append command provenance to `.agent_state/run_commands.md` when external
   commands were used.
7. Append a human-readable summary to `.agent_state/conversation_summary.md`
   when the decision trail would otherwise be hard to recover.

Never overwrite old lessons unless the user explicitly asks for cleanup. New
findings should be appended with a timestamp and source classification.

## Automation Script

Use the bundled script to extract factual candidates before writing a lesson:

```powershell
python <skill>/scripts/extract_native_log_experience.py `
  --workspace <workspace> `
  --output <workspace>/.agent_state/native_experience_extract.md
```

Use `--append` when preserving multiple extracts in one file:

```powershell
python <skill>/scripts/extract_native_log_experience.py `
  --workspace <workspace> `
  --output <workspace>/.agent_state/native_experience_extract.md `
  --append
```

The script reads:

- `.agent_state/current.json`
- `.agent_state/events.jsonl`
- `.agent_state/iterations/iter_*.json`

It also notes whether Codex-side supplement files exist. It does not modify the
workspace unless `--output` is provided, and it never edits `program.py`.

## Lesson Template

```markdown
## <YYYY-MM-DD HH:mm> <scene> <source-class>

- Workspace: `<path>`
- Run id: `<run_id or n/a>`
- Source files:
  - `.agent_state/events.jsonl`
  - `.agent_state/iterations/iter_00N.json`
  - `.agent_state/run_commands.md` if Codex-side commands were used
- Trigger:
  - <what failed or what was tested>
- Native agent decisions:
  - <supervisor/dev/evaluator facts from logs>
- Codex-side actions:
  - <commands or direct patches, or "none">
- Result:
  - <accuracy, missing fields, completed/failed status>
- Reusable lesson:
  - <short rule to apply next time>
- Next reuse instruction:
  - <what the next run should read or try first>
```

## Reuse Rule

Before testing a similar PDF or workspace, read the newest relevant lessons in:

```text
.agent_state/evolution_notes.md
.agent_state/run_commands.md
.agent_state/conversation_summary.md
```

Then verify against native logs if the lesson claims a native agentic repair.
Apply the lesson as a hypothesis, not as proof: run `xdev run` on the new
document and `xdev eval` on the baseline labels.
