# Feedback Loop

Use this format when talking to `agentic-extract` after a bad run.

## Standard Message Shape

1. Symptom: what is wrong.
2. Evidence: concrete doc IDs, fields, or evaluation results.
3. Cause: best current guess.
4. Fix target: what should change in `program.py` or business rules.
5. Verification: how to re-check the result.

## Example

```text
数字字段在多个样本里被漏提，evaluate 显示该字段准确率偏低。怀疑是字段名和格式化规则不稳定，请优先修正 program.py，并在 001.pdf 和 005.pdf 上复验。
```

## After Each Iteration

- update the workspace notes
- keep the best failure examples
- refine the next message instead of repeating the last one
