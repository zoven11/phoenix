from agentic_extract.evaluate import parse_xdev_eval_output


def test_parse_xdev_eval_output_populates_failing_fields():
    output = """
# 评估报告

总体准确率: 9.1%
字段平均准确率: 83.3%
文档数: 11
错误文档数: 10

| 字段 | 准确率 |
| --- | --- |
| is_audited | 100.0% |
| 派息比例[人民币] (10: X) | 18.2% |
| 主要财务指标 | 0.0% |
"""

    snapshot = parse_xdev_eval_output(output)

    assert snapshot is not None
    assert snapshot.failing_fields == ["派息比例[人民币] (10: X)", "主要财务指标"]
