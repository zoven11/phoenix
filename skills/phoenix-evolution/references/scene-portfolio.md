# Scene Portfolio

Use this file to decide whether a new document set can reuse an old scene.

## Reuse Signals

- Same document family: contract, notice, annual report, invoice, report, form.
- Same field intent: most requested fields map to the same business meaning.
- Similar layout and extraction difficulty.
- Same normalization rules or validation logic.

## Reuse Levels

1. Full reuse: copy `program.py` and adapt lightly.
2. Partial reuse: reuse parsing shape, prompts, or field rules.
3. Schema reuse only: reuse field definitions, then rebuild logic.
4. No reuse: start fresh.

## What To Compare

- `schema.json`
- `program.py`
- `business_guide.md`
- sample PDFs and failure cases

## Good Output

Always state:

- what scene was found
- why it matches or does not match
- what is reused
- what still needs fresh work
