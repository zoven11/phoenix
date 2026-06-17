"""Prompt formatting helpers for long-term evolution memory."""

from __future__ import annotations

from .models import EvolutionMemoryRecord


def render_memory_context(memories: list[EvolutionMemoryRecord]) -> str:
    """Render a compact prompt block for validated memories."""
    if not memories:
        return ""

    lines = [
        "以下是当前任务可复用的长期经验，请优先遵守这些经验和约束。",
    ]
    for memory in memories:
        lines.append("")
        lines.append(f"[{memory.memory_type}] {memory.title or memory.problem_pattern or memory.id}")
        if memory.source_pool:
            lines.append(f"经验池: {memory.source_pool}")
        if memory.document_family:
            lines.append(f"文档大类: {memory.document_family}")
        elif memory.document_category:
            lines.append(f"文档类别: {memory.document_category}")
        if memory.document_topic:
            lines.append(f"文档主题: {memory.document_topic}")
        if memory.field_group:
            lines.append(f"字段组: {memory.field_group}")
        failure_category = memory.failure_category or memory.category
        if failure_category:
            lines.append(f"失败分类: {failure_category}")
        if memory.field_name:
            lines.append(f"关联字段: {memory.field_name}")
        if memory.section_hint:
            lines.append(f"建议章节: {memory.section_hint}")
        if memory.position_hint:
            lines.append(f"建议位置: {memory.position_hint}")
        if memory.anchor_keywords:
            lines.append(f"锚点关键词: {'、'.join(memory.anchor_keywords[:5])}")
        if memory.canonical_examples:
            lines.append(f"典型值样例: {'；'.join(memory.canonical_examples[:3])}")
        if memory.normalization_rule:
            lines.append(f"归一规则: {memory.normalization_rule}")
        if memory.layout_pattern:
            lines.append(f"版式模式: {memory.layout_pattern}")
        if memory.applicable_conditions:
            lines.append(f"适用条件: {memory.applicable_conditions}")
        if memory.problem_pattern:
            lines.append(f"问题模式: {memory.problem_pattern}")
        if memory.evidence_refs:
            lines.append(f"证据摘要: {'; '.join(memory.evidence_refs[:4])}")
        if memory.recommended_action:
            lines.append(f"建议动作: {memory.recommended_action}")
        if memory.forbidden_action:
            lines.append(f"禁止事项: {memory.forbidden_action}")
    return "\n".join(lines).strip()
