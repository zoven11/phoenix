import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_incremental_pdf_reuse_test.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("run_incremental_pdf_reuse_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_extract_result_json_reads_xdev_run_output():
    module = _load_script_module()
    output = """
正在执行提取: doc-a

提取结果:
{
  "字段A": "value",
  "字段B": ""
}
"""

    result = module._extract_result_json(output)

    assert result == {"字段A": "value", "字段B": ""}


def test_render_report_states_pure_pdf_has_no_accuracy(tmp_path):
    module = _load_script_module()
    args = type(
        "Args",
        (),
        {
            "base_workspace": tmp_path / "base",
            "pdfs_dir": tmp_path / "pdfs",
        },
    )()
    result = module.IncrementResult(
        count=1,
        workspace=tmp_path / "workspace",
        doc_ids=["doc-a"],
        import_exit=0,
        run_results={"doc-a": {"字段A": "value", "字段B": ""}},
        run_exit_codes={"doc-a": 0},
        local_memory_count=1,
        local_usage_count=0,
        family_memory_count=2,
        topic_memory_count=3,
    )

    report = module.render_report(args, [result])

    assert "不补 label，因此不计算新增文档准确率" in report
    assert "1/1" in report
    assert "1 个非空字段" in report
    assert "family记忆数" in report
