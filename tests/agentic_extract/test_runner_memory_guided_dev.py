from agentic_extract.runner import _build_memory_guided_dev_task
from agentic_extract.state import EvaluationSnapshot, StateManager, SupervisorDecision


def test_build_memory_guided_dev_task_wraps_field_context():
    task = _build_memory_guided_dev_task(
        "修复会议投票方式字段",
        field_memory_context="关联字段: 会议投票方式\n锚点关键词: 现场表决、网络投票",
        failing_fields=["会议投票方式"],
    )

    assert "字段级经验快速修复模式" in task
    assert "当前失败字段: 会议投票方式" in task
    assert "锚点关键词: 现场表决、网络投票" in task
    assert "不要主动运行 xdev eval" in task
    assert "修复会议投票方式字段" in task


def test_build_memory_guided_dev_task_without_context_keeps_task():
    assert (
        _build_memory_guided_dev_task(
            "原始任务",
            field_memory_context="",
            failing_fields=["字段A"],
        )
        == "原始任务"
    )


def test_state_manager_returns_latest_formal_evaluation(tmp_path):
    state = StateManager(tmp_path)
    state.init()
    assert state.get_latest_evaluation() is None

    state.record_iteration(
        decision=SupervisorDecision(action="call_dev", task="修复代码"),
        summary="call_dev completed",
    )
    state.record_iteration(
        decision=SupervisorDecision(action="evaluate", task="正式评估"),
        evaluation=EvaluationSnapshot(
            accuracy=0.5,
            field_average=0.8,
            doc_count=2,
            error_count=1,
        ),
        summary="evaluate accuracy=50.0%",
    )
    state.record_iteration(
        decision=SupervisorDecision(action="call_business", task="检查标注"),
        summary="call_business completed",
    )

    latest = state.get_latest_evaluation()

    assert latest is not None
    assert latest.accuracy == 0.5
    assert latest.error_count == 1
