from types import SimpleNamespace

from agentic_extract.evolution_memory.category_pool import (
    canonicalize_document_category,
    canonicalize_document_topic,
    detect_document_category,
    write_category_detection,
)
from agentic_extract.evolution_memory.evidence import build_iteration_evidence
from agentic_extract.evolution_memory.prompt import render_memory_context
from agentic_extract.evolution_memory.runtime import EvolutionMemoryRuntime
from agentic_extract.evolution_memory.store import EvolutionMemoryStore
from agentic_extract.evolution_memory.summarize import build_field_candidates, build_run_candidate
from agentic_extract.evolution_memory.validate import promote_candidate


def test_failed_run_memory_records_fields_docs_and_category():
    evaluation = SimpleNamespace(
        accuracy=0.5,
        field_average=0.9167,
        doc_count=2,
        error_count=1,
        error_doc_ids=["1223321176"],
        field_accuracies={
            "公司名称": 1.0,
            "执行起始日期": 0.5,
        },
    )
    evidence = build_iteration_evidence(
        run_id="run-1",
        iteration=3,
        action="evaluate",
        summary="evaluate accuracy=50.0%",
        error=None,
        evaluation=evaluation,
        git_commit_before="before",
        git_commit_after="after",
    )

    candidate = build_run_candidate(
        run_id="run-1",
        evidence=[evidence],
        exit_reason="运行超时 (1200s)",
        completed=False,
        document_category="annual_report",
        document_family="annual_report",
        document_topic="audit_report",
        field_group="audit_fields",
    )
    memory = promote_candidate(candidate)

    assert evidence.failing_fields == ["执行起始日期"]
    assert evidence.error_doc_ids == ["1223321176"]
    assert candidate.category == "run_timeout"
    assert candidate.document_category == "annual_report"
    assert candidate.document_family == "annual_report"
    assert candidate.document_topic == "audit_report"
    assert candidate.field_group == "audit_fields"
    assert candidate.failure_category == "run_timeout"
    assert candidate.field_name == "执行起始日期"
    assert "failing_fields=执行起始日期" in candidate.evidence_refs
    assert "error_doc_ids=1223321176" in candidate.evidence_refs
    assert memory is not None
    assert memory.category == "run_timeout"
    assert memory.document_category == "annual_report"
    assert memory.document_family == "annual_report"
    assert memory.document_topic == "audit_report"
    assert memory.field_group == "audit_fields"
    assert memory.failure_category == "run_timeout"
    assert memory.field_name == "执行起始日期"
    assert memory.source_evidence_ids == [evidence.id]


def test_memory_prompt_renders_category_field_and_evidence():
    evaluation = SimpleNamespace(
        accuracy=0.5,
        field_average=0.9167,
        doc_count=2,
        error_count=1,
        error_doc_ids=["doc-a"],
        field_accuracies={"字段A": 0.5},
    )
    evidence = build_iteration_evidence(
        run_id="run-1",
        iteration=1,
        action="evaluate",
        summary="evaluate accuracy=50.0%",
        error=None,
        evaluation=evaluation,
        git_commit_before="",
        git_commit_after="",
    )
    candidate = build_run_candidate(
        run_id="run-1",
        evidence=[evidence],
        exit_reason="达到最大迭代次数 (3)",
        completed=False,
        document_category="bond_announcement",
        document_family="bond_announcement",
    )
    memory = promote_candidate(candidate)

    text = render_memory_context([memory])

    assert "文档大类: bond_announcement" in text
    assert "失败分类: max_iterations" in text
    assert "关联字段: 字段A" in text
    assert "failing_fields=字段A" in text


def test_build_field_candidates_creates_one_candidate_per_failing_field():
    evaluation = SimpleNamespace(
        accuracy=0.0,
        field_average=0.75,
        doc_count=1,
        error_count=1,
        error_doc_ids=["doc-a"],
        field_accuracies={"字段A": 0.0, "字段B": 0.5, "字段C": 1.0},
    )
    evidence = build_iteration_evidence(
        run_id="run-fields",
        iteration=1,
        action="evaluate",
        summary="evaluate accuracy=0.0%",
        error=None,
        evaluation=evaluation,
        git_commit_before="before",
        git_commit_after="after",
    )

    candidates = build_field_candidates(
        run_id="run-fields",
        evidence=[evidence],
        document_category="shareholder_meeting_notice",
        document_family="shareholder_meeting_notice",
        document_topic="shareholder_meeting_notice",
        field_group="shareholder_meeting_notice_fields",
    )

    assert [item.field_name for item in candidates] == ["字段A", "字段B"]
    assert all(item.category == "field_extraction_failure" for item in candidates)
    assert all("doc-a" in " ".join(item.evidence_refs) for item in candidates)


def test_build_field_candidates_include_location_hints_for_shareholder_notice():
    evaluation = SimpleNamespace(
        accuracy=0.5,
        field_average=0.5,
        doc_count=1,
        error_count=1,
        error_doc_ids=["doc-a"],
        field_accuracies={"会议投票方式": 0.0, "网络投票系统": 0.5},
    )
    evidence = build_iteration_evidence(
        run_id="run-location",
        iteration=1,
        action="evaluate",
        summary="evaluate accuracy=50.0%",
        error=None,
        evaluation=evaluation,
        git_commit_before="before",
        git_commit_after="after",
    )

    candidates = build_field_candidates(
        run_id="run-location",
        evidence=[evidence],
        document_category="shareholder_meeting_notice",
        document_family="shareholder_meeting_notice",
        document_topic="shareholder_meeting_notice",
        field_group="shareholder_meeting_notice_fields",
    )

    vote_memory = next(item for item in candidates if item.field_name == "会议投票方式")
    assert vote_memory.section_hint == "召开会议的基本情况"
    assert "前部" in (vote_memory.position_hint or "")
    assert "现场表决" in vote_memory.anchor_keywords
    assert vote_memory.canonical_examples
    assert vote_memory.normalization_rule
    assert vote_memory.layout_pattern


def test_runtime_selected_memories_for_fields_prioritizes_field_specific_entries(tmp_path):
    workspace_store = EvolutionMemoryStore(tmp_path / "workspace_memory")
    workspace_store.ensure_initialized()

    generic_memory = promote_candidate(
        build_run_candidate(
            run_id="run-generic",
            evidence=[
                build_iteration_evidence(
                    run_id="run-generic",
                    iteration=1,
                    action="evaluate",
                    summary="evaluate accuracy=50.0%",
                    error=None,
                        evaluation=SimpleNamespace(
                            accuracy=0.5,
                            field_average=0.5,
                            doc_count=1,
                            error_count=1,
                            error_doc_ids=["doc-a"],
                            field_accuracies={"字段A": 0.5, "字段Z": 0.5},
                        ),
                    git_commit_before="",
                    git_commit_after="",
                )
            ],
            exit_reason="达到最大迭代次数 (3)",
            completed=False,
            document_category="shareholder_meeting_notice",
            document_family="shareholder_meeting_notice",
            document_topic="shareholder_meeting_notice",
            field_group="shareholder_meeting_notice_fields",
        )
    ).model_copy(update={"id": "generic-memory", "quality_score": 0.7})
    workspace_store.append_memory(generic_memory)

    field_memory = promote_candidate(
        build_field_candidates(
            run_id="run-field",
            evidence=[
                build_iteration_evidence(
                    run_id="run-field",
                    iteration=1,
                    action="evaluate",
                    summary="evaluate accuracy=50.0%",
                    error=None,
                    evaluation=SimpleNamespace(
                        accuracy=0.5,
                        field_average=0.5,
                        doc_count=1,
                        error_count=1,
                        error_doc_ids=["doc-a"],
                        field_accuracies={"字段A": 0.5, "字段B": 1.0},
                    ),
                    git_commit_before="",
                    git_commit_after="",
                )
            ],
            document_category="shareholder_meeting_notice",
            document_family="shareholder_meeting_notice",
            document_topic="shareholder_meeting_notice",
            field_group="shareholder_meeting_notice_fields",
        )[0]
    ).model_copy(update={"id": "field-memory", "quality_score": 0.6})
    workspace_store.append_memory(field_memory)

    runtime = EvolutionMemoryRuntime(
        enabled=True,
        run_id="run-select",
        workspace_store=workspace_store,
        family_store=None,
        topic_store=None,
        top_k=8,
        document_category="shareholder_meeting_notice",
        document_family="shareholder_meeting_notice",
        document_topic="shareholder_meeting_notice",
        field_group="shareholder_meeting_notice_fields",
    )

    selections = runtime.selected_memories_for_fields(["字段A"])

    assert [item.memory.id for item in selections[:2]] == ["field-memory", "generic-memory"]


def test_runtime_finalize_run_populates_shared_pool_candidates_and_evidence(tmp_path):
    workspace_store = EvolutionMemoryStore(tmp_path / "workspace_memory")
    workspace_store.ensure_initialized()
    family_store = EvolutionMemoryStore(tmp_path / "family_memory")
    family_store.ensure_initialized()
    topic_store = EvolutionMemoryStore(tmp_path / "topic_memory")
    topic_store.ensure_initialized()

    evidence = build_iteration_evidence(
        run_id="run-finalize",
        iteration=1,
        action="evaluate",
        summary="evaluate accuracy=0.0%",
        error=None,
        evaluation=SimpleNamespace(
            accuracy=0.0,
            field_average=0.75,
            doc_count=1,
            error_count=1,
            error_doc_ids=["doc-a"],
            field_accuracies={"字段A": 0.0, "字段B": 1.0},
        ),
        git_commit_before="before",
        git_commit_after="after",
    )
    workspace_store.append_evidence(evidence)

    runtime = EvolutionMemoryRuntime(
        enabled=True,
        run_id="run-finalize",
        workspace_store=workspace_store,
        family_store=family_store,
        topic_store=topic_store,
        top_k=8,
        document_category="shareholder_meeting_notice",
        document_family="shareholder_meeting_notice",
        document_topic="shareholder_meeting_notice",
        field_group="shareholder_meeting_notice_fields",
    )

    runtime.finalize_run(exit_reason="达到最大迭代次数 (2)", completed=False)

    assert family_store.candidates_path.read_text(encoding="utf-8").strip()
    assert family_store.evidence_path.read_text(encoding="utf-8").strip()
    assert topic_store.candidates_path.read_text(encoding="utf-8").strip()
    assert topic_store.evidence_path.read_text(encoding="utf-8").strip()


def test_runtime_merges_workspace_family_and_topic_pools(tmp_path):
    workspace_store = EvolutionMemoryStore(tmp_path / "workspace_memory")
    workspace_store.ensure_initialized()
    family_store = EvolutionMemoryStore(tmp_path / "family_memory")
    family_store.ensure_initialized()
    topic_store = EvolutionMemoryStore(tmp_path / "topic_memory")
    topic_store.ensure_initialized()

    workspace_store.append_memory(
        promote_candidate(
            build_run_candidate(
                run_id="run-local",
                evidence=[
                    build_iteration_evidence(
                        run_id="run-local",
                        iteration=1,
                        action="evaluate",
                        summary="evaluate accuracy=90.0%",
                        error=None,
                        evaluation=SimpleNamespace(
                            accuracy=0.9,
                            field_average=0.9,
                            doc_count=1,
                            error_count=0,
                            error_doc_ids=[],
                            field_accuracies={"字段A": 0.9},
                        ),
                        git_commit_before="",
                        git_commit_after="",
                    )
                ],
                exit_reason="达到最大迭代次数 (3)",
                completed=False,
                document_category="annual_report",
                document_family="annual_report",
                document_topic="audit_report",
                field_group="audit_fields",
            )
        ).model_copy(update={"id": "workspace-memory", "quality_score": 0.7})
    )
    family_store.append_memory(
        promote_candidate(
            build_run_candidate(
                run_id="run-family",
                evidence=[
                    build_iteration_evidence(
                        run_id="run-family",
                        iteration=1,
                        action="evaluate",
                        summary="evaluate accuracy=95.0%",
                        error=None,
                        evaluation=SimpleNamespace(
                            accuracy=0.95,
                            field_average=0.95,
                            doc_count=1,
                            error_count=0,
                            error_doc_ids=[],
                            field_accuracies={"字段B": 0.95},
                        ),
                        git_commit_before="",
                        git_commit_after="",
                    )
                ],
                exit_reason="运行超时 (1200s)",
                completed=False,
                document_category="annual_report",
                document_family="annual_report",
            )
        ).model_copy(update={"id": "family-memory", "scope": "family", "quality_score": 0.9})
    )
    topic_store.append_memory(
        promote_candidate(
            build_run_candidate(
                run_id="run-topic",
                evidence=[
                    build_iteration_evidence(
                        run_id="run-topic",
                        iteration=1,
                        action="evaluate",
                        summary="evaluate accuracy=97.0%",
                        error=None,
                        evaluation=SimpleNamespace(
                            accuracy=0.97,
                            field_average=0.97,
                            doc_count=1,
                            error_count=0,
                            error_doc_ids=[],
                            field_accuracies={"字段C": 0.97},
                        ),
                        git_commit_before="",
                        git_commit_after="",
                    )
                ],
                exit_reason="运行超时 (1200s)",
                completed=False,
                document_category="annual_report",
                document_family="annual_report",
                document_topic="audit_report",
                field_group="audit_fields",
            )
        ).model_copy(update={"id": "topic-memory", "scope": "topic", "quality_score": 0.95})
    )

    runtime = EvolutionMemoryRuntime(
        enabled=True,
        run_id="run-merged",
        workspace_store=workspace_store,
        family_store=family_store,
        topic_store=topic_store,
        top_k=8,
        document_category="annual_report",
        document_family="annual_report",
        document_topic="audit_report",
        field_group="audit_fields",
    )

    selections = runtime.selected_memories()

    assert [item.memory.id for item in selections] == ["workspace-memory", "topic-memory", "family-memory"]

    text = runtime.build_initial_context()

    assert "经验池: workspace" in text
    assert "经验池: topic" in text
    assert "经验池: family" in text
    assert "文档大类: annual_report" in text
    assert "文档主题: audit_report" in text
    assert "字段组: audit_fields" in text


def test_memory_prompt_renders_field_location_hints():
    evaluation = SimpleNamespace(
        accuracy=0.5,
        field_average=0.5,
        doc_count=1,
        error_count=1,
        error_doc_ids=["doc-a"],
        field_accuracies={"会议投票方式": 0.5},
    )
    evidence = build_iteration_evidence(
        run_id="run-prompt-location",
        iteration=1,
        action="evaluate",
        summary="evaluate accuracy=50.0%",
        error=None,
        evaluation=evaluation,
        git_commit_before="",
        git_commit_after="",
    )
    candidate = build_field_candidates(
        run_id="run-prompt-location",
        evidence=[evidence],
        document_category="shareholder_meeting_notice",
        document_family="shareholder_meeting_notice",
        document_topic="shareholder_meeting_notice",
        field_group="shareholder_meeting_notice_fields",
    )[0]
    memory = promote_candidate(candidate)

    text = render_memory_context([memory])

    assert "建议章节: 召开会议的基本情况" in text
    assert "建议位置:" in text
    assert "锚点关键词:" in text
    assert "典型值样例:" in text
    assert "归一规则:" in text
    assert "版式模式:" in text


def test_detect_document_category_from_business_guide(tmp_path):
    (tmp_path / "business_guide.md").write_text(
        "# 业务指导\n\n1. **文档类型**：A股上市公司年度报告（PDF格式解析后的文本）\n",
        encoding="utf-8",
    )

    detection = detect_document_category(tmp_path)

    assert detection.category == "annual_report"
    assert detection.document_family == "annual_report"
    assert detection.document_topic is None
    assert detection.source == "business_guide_field"
    assert canonicalize_document_category("A股上市公司年度报告") == "annual_report"


def test_detect_document_category_from_schema_and_runtime_cache(tmp_path):
    xdev_dir = tmp_path / ".xdev"
    xdev_dir.mkdir(parents=True)
    (xdev_dir / "schema.json").write_text(
        '{"type":"object","data":{"is_audited":"bool","domestic_audit_opinion_type":"str","domestic_signing_cpas":"list","domestic_audit_firm_name":"str"}}',
        encoding="utf-8",
    )

    detection = detect_document_category(tmp_path)
    assert detection.category == "annual_report"
    assert detection.document_family == "annual_report"
    assert detection.document_topic == "audit_report"
    assert detection.field_group == "audit_fields"
    assert detection.source == "schema_signature"
    assert canonicalize_document_topic("审计报告") == "audit_report"

    runtime_root = tmp_path / ".phoenix_memory"
    write_category_detection(
        runtime_root,
        detection,
    )
    cached = detect_document_category(tmp_path, runtime_root=runtime_root)
    assert cached.category == "annual_report"
    assert cached.document_family == "annual_report"
    assert cached.document_topic == "audit_report"
    assert cached.source == "schema_signature"


def test_detect_document_category_for_civil_ruling_workspace(tmp_path):
    (tmp_path / "business_guide.md").write_text(
        "# 业务指导文档\n\n## 数据集概述\n\n本数据集包含最高人民法院发布的法律文书，主要包括民事裁定书和民事判决书两类。\n",
        encoding="utf-8",
    )
    xdev_dir = tmp_path / ".xdev"
    xdev_dir.mkdir(parents=True)
    (xdev_dir / "schema.json").write_text(
        '{"type":"object","data":{"案号":"str","文书类型":"str","再审申请人":"str","被申请人":"str","原审法院":"str","案由":"str","裁定结果":"str","审判长":"str","审判员":"str","裁定日期":"str"}}',
        encoding="utf-8",
    )

    detection = detect_document_category(tmp_path)

    assert detection.category == "judicial_document"
    assert detection.document_family == "judicial_document"
    assert detection.document_topic == "civil_ruling"
    assert detection.field_group == "judicial_case_fields"
    assert detection.source == "business_guide_keywords+schema_signature"
