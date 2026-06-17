"""Rule-based summarization from evidence to candidate memories."""

from __future__ import annotations

import uuid

from .models import EvolutionMemoryCandidate, EvolutionMemoryEvidence


def _latest_evaluation(evidence: list[EvolutionMemoryEvidence]) -> EvolutionMemoryEvidence | None:
    evaluated = [item for item in evidence if item.accuracy is not None]
    return evaluated[-1] if evaluated else None


def _classify_failure(
    *,
    exit_reason: str,
    latest: EvolutionMemoryEvidence,
    latest_eval: EvolutionMemoryEvidence | None,
) -> str:
    reason = exit_reason or ""
    if "运行超时" in reason or "timeout" in reason.lower():
        return "run_timeout"
    if "最大迭代次数" in reason or "max iteration" in reason.lower():
        return "max_iterations"
    if latest.error:
        return "tool_or_runtime_error"
    if latest_eval and latest_eval.failing_fields:
        return "field_extraction_failure"
    if latest_eval and latest_eval.accuracy is not None and latest_eval.accuracy < 1.0:
        return "evaluation_regression"
    return "interrupted_run"


def _recommended_action_for_failure(
    category: str,
    latest_eval: EvolutionMemoryEvidence | None,
) -> tuple[str, str]:
    if category == "run_timeout":
        return (
            "Use a narrower repair step: DevAgent should inspect failing fields and run targeted `xdev run <doc_id>` only; leave full `xdev eval` to the runner.",
            "Do not let DevAgent repeatedly run full `xdev eval` during repair.",
        )
    if category == "max_iterations":
        return (
            "Review the last evaluation summary and re-run with a narrower task or an earlier evaluate step.",
            "Do not continue multiple development iterations without re-checking evaluation.",
        )
    if category == "field_extraction_failure" and latest_eval is not None:
        fields = ", ".join(latest_eval.failing_fields) or "unknown fields"
        docs = ", ".join(latest_eval.error_doc_ids[:5]) or "unknown docs"
        return (
            f"Target the failing fields ({fields}) on error docs ({docs}) with `xdev run <doc_id>` before requesting a full evaluate.",
            "Do not rewrite unrelated schema, labels, or already-passing fields.",
        )
    if category == "tool_or_runtime_error":
        return (
            "Inspect the tool/runtime error first, then make the smallest code or workflow fix needed before evaluating again.",
            "Do not treat a tool/runtime failure as a business-label problem without evidence.",
        )
    return (
        "Review the last iteration summary and evaluate from the latest stable checkpoint.",
        "Do not discard the last validated checkpoint before comparing accuracy.",
    )


def _base_applicable_conditions(
    *,
    document_category: str | None,
    document_family: str | None,
    document_topic: str | None,
) -> str:
    if not (document_family or document_topic or document_category):
        return "Applies to subsequent runs in the same workspace."
    return (
        "Applies to subsequent runs in the same workspace or same document family/topic "
        f"({document_family or document_category}"
        + (f" / {document_topic}" if document_topic else "")
        + ")."
    )


def _field_location_profile(
    *,
    document_category: str | None,
    document_family: str | None,
    document_topic: str | None,
    field_name: str,
) -> dict[str, object]:
    if document_topic == "shareholder_meeting_notice" or document_family == "shareholder_meeting_notice":
        profiles: dict[str, dict[str, object]] = {
            "会议投票方式": {
                "section_hint": "召开会议的基本情况",
                "position_hint": "通常位于公告前部、标题后基础信息段落",
                "anchor_keywords": ["现场表决", "网络投票", "现场投票", "相结合方式"],
                "canonical_examples": ["现场投票与网络投票相结合", "仅采用现场投票", "采用网络投票与现场投票结合的方式"],
                "normalization_rule": "优先抽取投票方式的完整组合描述，保留‘现场/网络’并列结构。",
                "layout_pattern": "标题后首个信息段，常跟随会议时间、地点、股权登记日。",
            },
            "网络投票系统": {
                "section_hint": "召开会议的基本情况",
                "position_hint": "紧邻会议投票方式说明，通常在前半段出现",
                "anchor_keywords": ["网络投票系统", "深交所交易系统", "互联网投票系统"],
                "canonical_examples": ["深交所交易系统和互联网投票系统", "深圳证券交易所交易系统", "互联网投票系统"],
                "normalization_rule": "保留交易所名称和系统全称，不要缩写成单个词。",
                "layout_pattern": "投票方式之后的补充说明句。",
            },
            "股权登记日": {
                "section_hint": "召开会议的基本情况",
                "position_hint": "通常与会议时间、地点、股东登记日并列出现",
                "anchor_keywords": ["股权登记日", "登记日"],
                "canonical_examples": ["2024年5月20日", "2024-05-20", "股权登记日为2024年5月20日"],
                "normalization_rule": "保留原始日期格式，并统一到日期字段可解析表达。",
                "layout_pattern": "基础信息段中的日期字段。",
            },
        }
        return profiles.get(
            field_name,
            {
                "section_hint": "召开会议的基本情况",
                "position_hint": "通常位于文档前部基础信息段",
                "anchor_keywords": [field_name],
                "canonical_examples": [],
                "normalization_rule": "结合标题附近和基础信息段上下文提取。",
                "layout_pattern": "公告前部基础信息段。",
            },
        )
    return {
        "section_hint": None,
        "position_hint": None,
        "anchor_keywords": [field_name],
        "canonical_examples": [],
        "normalization_rule": None,
        "layout_pattern": None,
    }


def build_run_candidate(
    *,
    run_id: str,
    evidence: list[EvolutionMemoryEvidence],
    exit_reason: str,
    completed: bool,
    document_category: str | None = None,
    document_family: str | None = None,
    document_topic: str | None = None,
    field_group: str | None = None,
) -> EvolutionMemoryCandidate | None:
    """Build a conservative candidate memory from the latest run evidence."""
    if not evidence:
        return None

    latest = evidence[-1]
    evaluated = [item for item in evidence if item.accuracy is not None]
    latest_eval = _latest_evaluation(evidence)
    best_accuracy = max((item.accuracy for item in evaluated if item.accuracy is not None), default=None)
    last_accuracy = latest_eval.accuracy if latest_eval is not None else latest.accuracy

    if completed and best_accuracy is not None:
        title = "Stable workflow pattern from completed run"
        problem_pattern = "A completed run reached a validated evaluation checkpoint."
        recommended_action = (
            "When a similar workspace enters repair mode, start from the last validated "
            "evaluation checkpoint before broad changes."
        )
        forbidden_action = "Do not discard the last validated checkpoint before comparing accuracy."
        evidence_refs = [f"best_accuracy={best_accuracy:.1%}"]
        category = "completed_checkpoint"
        field_name = None
    else:
        category = _classify_failure(
            exit_reason=exit_reason,
            latest=latest,
            latest_eval=latest_eval,
        )
        title = "Failure pattern from interrupted run"
        problem_pattern = exit_reason or latest.summary or "Run failed before stable completion."
        if latest_eval and latest_eval.failing_fields:
            problem_pattern = (
                f"{problem_pattern}; failing_fields={', '.join(latest_eval.failing_fields)}"
            )
        recommended_action, forbidden_action = _recommended_action_for_failure(
            category,
            latest_eval,
        )
        evidence_refs = [f"last_summary={latest.summary}"] if latest.summary else []
        field_name = (
            latest_eval.failing_fields[0]
            if latest_eval is not None and len(latest_eval.failing_fields) == 1
            else None
        )

    if last_accuracy is not None:
        evidence_refs.append(f"last_accuracy={last_accuracy:.1%}")
    if latest_eval is not None:
        if latest_eval.field_average is not None:
            evidence_refs.append(f"field_average={latest_eval.field_average:.1%}")
        if latest_eval.failing_fields:
            evidence_refs.append(f"failing_fields={', '.join(latest_eval.failing_fields)}")
        if latest_eval.error_doc_ids:
            evidence_refs.append(f"error_doc_ids={', '.join(latest_eval.error_doc_ids[:5])}")

    return EvolutionMemoryCandidate(
        id=uuid.uuid4().hex,
        run_id=run_id,
        title=title,
        scope="workspace",
        memory_type="strategy",
        field_name=field_name,
        category=category,
        document_category=document_category,
        document_family=document_family or document_category,
        document_topic=document_topic,
        field_group=field_group,
        failure_category=category,
        problem_pattern=problem_pattern,
        applicable_conditions=_base_applicable_conditions(
            document_category=document_category,
            document_family=document_family,
            document_topic=document_topic,
        ),
        recommended_action=recommended_action,
        forbidden_action=forbidden_action,
        evidence_refs=evidence_refs,
        source_evidence_ids=[item.id for item in evidence[-5:]],
    )


def build_field_candidates(
    *,
    run_id: str,
    evidence: list[EvolutionMemoryEvidence],
    document_category: str | None = None,
    document_family: str | None = None,
    document_topic: str | None = None,
    field_group: str | None = None,
) -> list[EvolutionMemoryCandidate]:
    """Build per-field candidates from the latest evaluated failure snapshot."""
    latest_eval = _latest_evaluation(evidence)
    if latest_eval is None or not latest_eval.failing_fields:
        return []

    candidates: list[EvolutionMemoryCandidate] = []
    docs = ", ".join(latest_eval.error_doc_ids[:5]) or "unknown docs"
    accuracy_text = (
        f"{latest_eval.accuracy:.1%}" if latest_eval.accuracy is not None else "unknown"
    )
    field_avg_text = (
        f"{latest_eval.field_average:.1%}" if latest_eval.field_average is not None else "unknown"
    )
    for field_name in latest_eval.failing_fields:
        location = _field_location_profile(
            document_category=document_category,
            document_family=document_family,
            document_topic=document_topic,
            field_name=field_name,
        )
        candidates.append(
            EvolutionMemoryCandidate(
                id=uuid.uuid4().hex,
                run_id=run_id,
                title=f"Field repair pattern: {field_name}",
                scope="workspace",
                memory_type="strategy",
                field_name=field_name,
                category="field_extraction_failure",
                document_category=document_category,
                document_family=document_family or document_category,
                document_topic=document_topic,
                field_group=field_group,
                failure_category="field_extraction_failure",
                section_hint=location["section_hint"],
                position_hint=location["position_hint"],
                anchor_keywords=list(location["anchor_keywords"]),
                canonical_examples=list(location["canonical_examples"]),
                normalization_rule=location["normalization_rule"],
                layout_pattern=location["layout_pattern"],
                problem_pattern=(
                    f"Field `{field_name}` failed in evaluation; "
                    f"overall_accuracy={accuracy_text}; field_average={field_avg_text}"
                ),
                applicable_conditions=_base_applicable_conditions(
                    document_category=document_category,
                    document_family=document_family,
                    document_topic=document_topic,
                ),
                recommended_action=(
                    f"Before broad repair, inspect field `{field_name}` on failing docs ({docs}) "
                    "with `xdev run <doc_id>` and constrain the fix to this field first."
                ),
                forbidden_action=(
                    f"Do not rewrite unrelated fields when only `{field_name}` is failing."
                ),
                evidence_refs=[
                    f"field_name={field_name}",
                    f"last_accuracy={accuracy_text}",
                    f"field_average={field_avg_text}",
                    f"error_doc_ids={docs}",
                ],
                source_evidence_ids=[latest_eval.id],
            )
        )
    return candidates
