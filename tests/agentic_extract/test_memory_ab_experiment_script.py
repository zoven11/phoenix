import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_memory_ab_experiment.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("run_memory_ab_experiment", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_collect_workspace_metrics_reads_accuracy_and_memory_usage(tmp_path):
    module = _load_script_module()
    workspace = tmp_path / "workspace"
    _write_json(
        workspace / ".agent_state" / "current.json",
        {
            "current_iteration": 2,
            "status": "completed",
            "total_run_duration_sec": 12.5,
        },
    )
    _write_json(
        workspace / ".agent_state" / "iterations" / "iter_001.json",
        {
            "evaluation": {
                "accuracy": 0.5,
                "field_average": 0.75,
                "doc_count": 2,
                "error_count": 1,
                "field_accuracies": {"字段A": 0.0, "字段B": 1.0},
            }
        },
    )
    _write_json(
        workspace / ".agent_state" / "iterations" / "iter_002.json",
        {
            "evaluation": {
                "accuracy": 1.0,
                "field_average": 1.0,
                "doc_count": 2,
                "error_count": 0,
                "field_accuracies": {"字段A": 1.0, "字段B": 1.0},
            }
        },
    )
    _write_jsonl(
        workspace / ".phoenix_memory" / "usage.jsonl",
        [{"run_id": "run-1", "memory_ids": ["m1", "m2", "m1"]}],
    )
    _write_jsonl(workspace / ".phoenix_memory" / "memories.jsonl", [{"id": "m1"}])
    _write_jsonl(workspace / ".phoenix_memory" / "candidates.jsonl", [{"id": "c1"}])
    _write_jsonl(workspace / ".phoenix_memory" / "evidence.jsonl", [{"id": "e1"}])

    metrics = module.collect_workspace_metrics("B", workspace)

    assert metrics.status == "completed"
    assert metrics.iterations == 2
    assert metrics.initial_eval.accuracy == 0.5
    assert metrics.final_eval.accuracy == 1.0
    assert metrics.final_eval.failing_fields == []
    assert metrics.memory_usage_events == 1
    assert metrics.used_memory_ids == ["m1", "m2"]
    assert metrics.memory_records == 1
    assert metrics.candidate_records == 1
    assert metrics.evidence_records == 1


def test_render_report_includes_memory_usage_summary(tmp_path):
    module = _load_script_module()
    no_memory = module.WorkspaceMetrics(
        name="A",
        workspace=tmp_path / "no-memory",
        status="failed",
        error="达到最大迭代次数",
        iterations=2,
        duration_sec=10.0,
        initial_eval=module.EvaluationMetrics(accuracy=0.0, field_average=0.5),
        final_eval=module.EvaluationMetrics(
            accuracy=0.5,
            field_average=0.75,
            error_count=1,
            failing_fields=["字段A"],
        ),
        memory_usage_events=0,
        used_memory_ids=[],
        memory_records=0,
        candidate_records=0,
        evidence_records=0,
    )
    with_memory = module.WorkspaceMetrics(
        name="B",
        workspace=tmp_path / "with-memory",
        status="completed",
        error=None,
        iterations=1,
        duration_sec=8.0,
        initial_eval=module.EvaluationMetrics(accuracy=0.0, field_average=0.5),
        final_eval=module.EvaluationMetrics(
            accuracy=1.0,
            field_average=1.0,
            error_count=0,
            failing_fields=[],
        ),
        memory_usage_events=2,
        used_memory_ids=["m1"],
        memory_records=3,
        candidate_records=4,
        evidence_records=5,
    )
    args = type(
        "Args",
        (),
        {
            "pdfs_dir": tmp_path / "pdfs",
            "data_dir": None,
            "source_file": None,
            "memory_global_dir": tmp_path / "memory_pool",
            "budget": "fast",
            "max_iterations": 2,
        },
    )()

    report = module.render_report(
        args=args,
        no_memory=no_memory,
        with_memory=with_memory,
        no_memory_exit=1,
        with_memory_exit=0,
    )

    assert "Phoenix 长期记忆 A/B 实验报告" in report
    assert "| B | 开启 | 0 | completed" in report
    assert "100.00%" in report
    assert "有经验组 usage 事件数: `2`" in report
    assert "m1" in report
