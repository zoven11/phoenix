from agentic_extract.extract_result import save_extract_results_for_labels


def test_save_extract_results_for_labels_writes_label_sibling_results(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    labels = workspace / ".xdev" / "labels"
    labels.mkdir(parents=True)
    (labels / "doc-b.json").write_text("{}", encoding="utf-8")
    (labels / "doc-a.json").write_text("{}", encoding="utf-8")

    calls = []

    def fake_run_single_extraction(doc_id, *, data_dir=None, workspace=None):
        calls.append((doc_id, data_dir, workspace))
        return {"field": doc_id}

    monkeypatch.setattr("xdev.evaluation.run_single_extraction", fake_run_single_extraction)

    summary = save_extract_results_for_labels(workspace)

    output_dir = workspace / ".xdev" / "extract_result"
    assert summary.total_count == 2
    assert summary.success_count == 2
    assert summary.failed == {}
    assert summary.output_dir == output_dir.resolve()
    assert (output_dir / "doc-a.json").read_text(encoding="utf-8") == '{\n  "field": "doc-a"\n}\n'
    assert (output_dir / "doc-b.json").read_text(encoding="utf-8") == '{\n  "field": "doc-b"\n}\n'
    assert (output_dir / "_summary.json").exists()
    assert [item[0] for item in calls] == ["doc-a", "doc-b"]
