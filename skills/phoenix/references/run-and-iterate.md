# Run and Iterate

## First Run From PDFs

Put PDFs in one directory:

```text
pdfs/
  001.pdf
  002.pdf
  003.pdf
```

Then run:

```bash
agentic-extract auto \
  --workspace ws \
  --pdfs-dir ./pdfs \
  --budget full \
  --message '提取发票号码、购买方、销售方、金额、开票日期'
```

Use `auto` when the workspace is new or `.xdev` data has not been prepared.

## Continue an Existing Workspace

```bash
agentic-extract run \
  --workspace ws \
  --budget full \
  --message '购买方名称提取不稳定，继续优化并评估'
```

Use natural-language feedback in `--message`; mention the bad field, wrong examples, or target behavior.

## Budget

Default for complete extraction tasks:

```bash
agentic-extract run --workspace ws --budget full
```

Quick experiment:

```bash
agentic-extract run --workspace ws --budget fast
```

Deeper iteration:

```bash
agentic-extract run --workspace ws --budget full
```

Explicit limits:

```bash
agentic-extract run \
  --workspace ws \
  --max-iterations 5 \
  --agent-max-iters 12
```

## Typical Loop

1. `agentic-extract auto` creates and improves the first extraction program.
2. `xdev run --workspace ws --pdf ./pdfs/001.pdf` checks concrete output.
3. `xdev evaluate --workspace ws` checks aggregate quality.
4. `agentic-extract run --workspace ws --budget full --message '...'` continues improvement.

## Generalization Failure Loop

When a reused workspace fails on a new PDF, prefer a full Phoenix iteration
instead of only patching files manually:

1. Use `xdev run` to capture the failing output.
2. Confirm from the PDF text that the missing fields exist.
3. Summarize the failure with concrete evidence.
4. Run `agentic-extract run --workspace ws --budget full --message '...'` to let the Phoenix
   agent revise the extractor and record the iteration in `.agent_state/`.
5. Re-run the failed PDF with `xdev run`.
6. Re-run the original labels with `xdev eval` or `xdev evaluate`.

Use direct `program.py` edits only for explicit manual fixes, emergency hotfixes,
or when `agentic-extract` is unavailable.

## Waiting for Runs

`agentic-extract` can run for a long time. Keep progress visible:

- Prefer foreground execution and poll stdout.
- If the process was backgrounded, tail `ws/.agent_state/events.jsonl`.
- Use `skills/phoenix/scripts/watch_phoenix_events.sh ws` for a consistent tail command.
- When reporting to the user, include latest iteration, step, decision, heartbeat, token usage, and completion/failure status.
