"""Locate extraction result values back to Document source positions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable

from code_executor.document.models.base import BBox
from code_executor.document.models.document import Document
from code_executor.document.models.nodes import HeadingNode, ParagraphNode, TableNode

_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class SourceLocation:
    """A source text unit with page, node, and geometry metadata."""

    text: str
    page: int
    bbox: list[float] | None
    node_id: Any
    node_type: str
    line_index: int
    line_number: int
    chapter_path: list[str]
    row_index: int | None = None
    col_index: int | None = None


def _normalize(value: Any) -> str:
    return _WHITESPACE_RE.sub("", str(value).strip()).lower()


def _bbox_to_list(bbox: BBox | None) -> list[float] | None:
    if bbox is None:
        return None
    return [bbox.x0, bbox.y0, bbox.x1, bbox.y1]


def _chapter_path(node: Any) -> list[str]:
    ancestors = node.get_ancestors() if hasattr(node, "get_ancestors") else []
    path: list[str] = []
    for ancestor in ancestors:
        title = ancestor.get_title()
        if title:
            path.append(title)
    if isinstance(node, HeadingNode):
        title = node.get_title()
        if title:
            path.append(title)
    return path


def flatten_document_sources(document: Document) -> list[SourceLocation]:
    """Flatten a Document into searchable source locations."""
    page_line_counts: dict[int, int] = {}
    sources: list[SourceLocation] = []

    for node in document.iter_nodes():
        if isinstance(node, (HeadingNode, ParagraphNode)):
            textlines = getattr(node, "textlines", []) or []
            if not textlines and node.get_text():
                page = node.page_number
                page_line_counts[page] = page_line_counts.get(page, 0) + 1
                sources.append(SourceLocation(
                    text=node.get_text(),
                    page=page,
                    bbox=None,
                    node_id=node.id,
                    node_type=node.type,
                    line_index=0,
                    line_number=page_line_counts[page],
                    chapter_path=_chapter_path(node),
                ))
                continue

            for line_index, textline in enumerate(textlines):
                text = textline.text.strip()
                if not text:
                    continue
                page = textline.page_number or node.page_number
                page_line_counts[page] = page_line_counts.get(page, 0) + 1
                sources.append(SourceLocation(
                    text=text,
                    page=page,
                    bbox=_bbox_to_list(textline.bbox),
                    node_id=node.id,
                    node_type=node.type,
                    line_index=line_index,
                    line_number=page_line_counts[page],
                    chapter_path=_chapter_path(node),
                ))

        elif isinstance(node, TableNode):
            for cell in node.cells:
                text = cell.text.strip()
                if not text:
                    continue
                page = cell.page_number or node.page_number
                page_line_counts[page] = page_line_counts.get(page, 0) + 1
                sources.append(SourceLocation(
                    text=text,
                    page=page,
                    bbox=_bbox_to_list(cell.bbox),
                    node_id=node.id,
                    node_type=node.type,
                    line_index=page_line_counts[page] - 1,
                    line_number=page_line_counts[page],
                    chapter_path=_chapter_path(node),
                    row_index=cell.row_index,
                    col_index=cell.col_index,
                ))

    return sources


def _source_to_dict(source: SourceLocation, match_type: str, confidence: float) -> dict[str, Any]:
    item: dict[str, Any] = {
        "page": source.page,
        "node_id": source.node_id,
        "node_type": source.node_type,
        "line_number": source.line_number,
        "line_index": source.line_index,
        "line_text": source.text,
        "bbox": source.bbox,
        "chapter_path": source.chapter_path,
        "match_type": match_type,
        "confidence": round(confidence, 4),
    }
    if source.row_index is not None:
        item["row_index"] = source.row_index
    if source.col_index is not None:
        item["col_index"] = source.col_index
    return item


def locate_value_sources(
    value: Any,
    sources: list[SourceLocation],
    *,
    max_matches: int = 3,
    fuzzy_threshold: float = 0.72,
) -> list[dict[str, Any]]:
    """Locate one scalar value in source locations."""
    if value is None or isinstance(value, (dict, list)):
        return []

    normalized_value = _normalize(value)
    if not normalized_value:
        return []

    exact_matches: list[dict[str, Any]] = []
    fuzzy_candidates: list[tuple[float, SourceLocation]] = []

    for source in sources:
        normalized_line = _normalize(source.text)
        if not normalized_line:
            continue
        if normalized_value in normalized_line:
            exact_matches.append(_source_to_dict(source, "exact", 1.0))
            if len(exact_matches) >= max_matches:
                return exact_matches
            continue
        ratio = SequenceMatcher(None, normalized_value, normalized_line).ratio()
        if ratio >= fuzzy_threshold:
            fuzzy_candidates.append((ratio, source))

    if exact_matches:
        return exact_matches

    fuzzy_candidates.sort(key=lambda item: item[0], reverse=True)
    return [
        _source_to_dict(source, "fuzzy", ratio)
        for ratio, source in fuzzy_candidates[:max_matches]
    ]


def _iter_result_values(value: Any, path: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield from _iter_result_values(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]" if path else f"[{index}]"
            yield from _iter_result_values(child, child_path)
    else:
        yield path, value


def locate_result_sources(
    result: Any,
    document: Document,
    *,
    max_matches_per_field: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """Locate all scalar leaves from an extraction result in a Document."""
    flat_sources = flatten_document_sources(document)
    if not flat_sources:
        return {}

    located: dict[str, list[dict[str, Any]]] = {}
    for field_path, value in _iter_result_values(result):
        matches = locate_value_sources(
            value,
            flat_sources,
            max_matches=max_matches_per_field,
        )
        if matches:
            located[field_path] = matches
    return located


def locate_result_sources_from_docjson(
    result: Any,
    docjson: dict[str, Any],
    *,
    max_matches_per_field: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """Build a Document from docjson and locate result sources."""
    document = Document.from_dict(docjson)
    return locate_result_sources(
        result,
        document,
        max_matches_per_field=max_matches_per_field,
    )
