"""Category-aware helpers for shared evolution memory pools."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


_CATEGORY_PATTERNS = [
    re.compile(r"[*#\-\d\.\s]*(?:文档类型|文档类别|业务类别|document[_ ]category|category)[* ]*\s*[:：]\s*(.+)", re.IGNORECASE),
]

_FAMILY_ALIASES = {
    "annual_report": [
        "annual_report",
        "annual-report",
        "year_report",
        "年报",
        "年度报告",
        "a股上市公司年度报告",
        "上市公司年度报告",
    ],
    "bond_announcement": [
        "bond_announcement",
        "bond-announcement",
        "债券",
        "债券公告",
        "债券类公告",
    ],
    "correction_announcement": [
        "correction_announcement",
        "correction-announcement",
        "更正",
        "更正公告",
    ],
    "restructure_announcement": [
        "restructure_announcement",
        "restructure-announcement",
        "重组",
        "重组公告",
    ],
    "judicial_document": [
        "judicial_document",
        "judicial-document",
        "court_case",
        "court-case",
        "法律文书",
        "司法文书",
        "裁判文书",
        "法院文书",
        "民事裁定书",
        "民事判决书",
    ],
    "shareholder_meeting_notice": [
        "shareholder_meeting_notice",
        "shareholder-meeting-notice",
        "shareholders_meeting_notice",
        "shareholders-meeting-notice",
        "股东大会通知",
        "股东大会召开通知",
        "股东大会提示性公告",
        "召开股东大会通知",
        "召开股东大会的通知",
    ],
}

_TOPIC_DEFINITIONS = {
    "audit_report": {
        "family": "annual_report",
        "field_group": "audit_fields",
        "aliases": [
            "audit_report",
            "audit-report",
            "审计报告",
            "审计信息",
            "审计意见",
            "年报审计",
        ],
    },
    "annual_report_universal": {
        "family": "annual_report",
        "field_group": "annual_report_multi_module",
        "aliases": [
            "annual_report_universal",
            "annual-report-universal",
            "年报通用",
            "通用年报",
            "年报多字段",
            "年度报告通用抽取",
        ],
    },
    "financial_statements": {
        "family": "annual_report",
        "field_group": "financial_statement_fields",
        "aliases": [
            "financial_statements",
            "financial-statements",
            "三大报表",
            "财务报表",
            "资产负债表",
            "利润表",
            "现金流量表",
        ],
    },
    "dividend_and_bonus_issue": {
        "family": "annual_report",
        "field_group": "dividend_fields",
        "aliases": [
            "dividend_and_bonus_issue",
            "dividend-and-bonus-issue",
            "分红转增",
            "利润分配",
            "现金分红",
            "送股转增",
        ],
    },
    "civil_ruling": {
        "family": "judicial_document",
        "field_group": "judicial_case_fields",
        "aliases": [
            "civil_ruling",
            "civil-ruling",
            "民事裁定书",
            "裁定书",
            "民事裁定",
        ],
    },
    "civil_judgment": {
        "family": "judicial_document",
        "field_group": "judicial_case_fields",
        "aliases": [
            "civil_judgment",
            "civil-judgment",
            "民事判决书",
            "判决书",
            "民事判决",
        ],
    },
    "shareholder_meeting_notice": {
        "family": "shareholder_meeting_notice",
        "field_group": "shareholder_meeting_notice_fields",
        "aliases": [
            "shareholder_meeting_notice",
            "shareholder-meeting-notice",
            "股东大会通知",
            "股东大会召开通知",
            "股东大会提示性公告",
            "关于召开股东大会的通知",
            "关于召开年度股东大会的提示性公告",
            "关于召开临时股东大会的通知",
        ],
    },
}

_SCHEMA_FAMILY_SIGNATURES = {
    "annual_report": {
        "is_audited",
        "domestic_audit_opinion_type",
        "domestic_signing_cpas",
        "domestic_audit_firm_name",
    },
}

_SCHEMA_TOPIC_SIGNATURES = {
    "audit_report": {
        "is_audited",
        "domestic_audit_opinion_type",
        "domestic_signing_cpas",
        "domestic_audit_firm_name",
    },
    "civil_ruling": {
        "案号",
        "文书类型",
        "再审申请人",
        "被申请人",
        "原审法院",
        "案由",
        "裁定结果",
        "审判长",
        "审判员",
        "裁定日期",
    },
    "shareholder_meeting_notice": {
        "公司名称",
        "会议召开日期",
        "会议投票方式",
        "审议议案名称",
        "审议议案数量",
        "网络投票系统",
        "股东大会届次",
        "股东大会类型",
        "重要内容提示",
    },
}


@dataclass(frozen=True)
class CategoryDetection:
    category: str | None
    document_family: str | None
    document_topic: str | None
    field_group: str | None
    source: str
    raw_value: str | None = None


def normalize_category_slug(value: str | None) -> str | None:
    """Normalize a business category into a stable slug."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    slug = text.lower()
    slug = re.sub(r"[\s/]+", "_", slug)
    slug = re.sub(r"[^0-9a-z_\-\u4e00-\u9fff]+", "", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or None


def canonicalize_document_family(value: str | None, *, allow_unknown: bool = False) -> str | None:
    """Map free-form family text to a stable family slug when possible."""
    slug = normalize_category_slug(value)
    if slug is None:
        return None
    for canonical, aliases in _FAMILY_ALIASES.items():
        if slug == canonical:
            return canonical
        for alias in aliases:
            alias_slug = normalize_category_slug(alias)
            if alias_slug and (slug == alias_slug or alias_slug in slug or slug in alias_slug):
                return canonical
    return slug if allow_unknown else None


def canonicalize_document_category(value: str | None) -> str | None:
    """Backward-compatible alias for canonicalize_document_family."""
    return canonicalize_document_family(value, allow_unknown=True)


def canonicalize_document_topic(value: str | None) -> str | None:
    """Map free-form topic text to a stable topic slug when possible."""
    slug = normalize_category_slug(value)
    if slug is None:
        return None
    for canonical, definition in _TOPIC_DEFINITIONS.items():
        if slug == canonical:
            return canonical
        for alias in definition["aliases"]:
            alias_slug = normalize_category_slug(alias)
            if alias_slug and (slug == alias_slug or alias_slug in slug or slug in alias_slug):
                return canonical
    return None


def _detect_from_runtime_cache(runtime_root: Path) -> CategoryDetection | None:
    cache_path = runtime_root / "document_category.json"
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    document_family = canonicalize_document_family(
        payload.get("document_family") or payload.get("category")
    )
    document_topic = canonicalize_document_topic(payload.get("document_topic"))
    field_group = normalize_category_slug(payload.get("field_group"))
    category = document_family
    if not document_family and not document_topic:
        return None
    return CategoryDetection(
        category=category,
        document_family=document_family,
        document_topic=document_topic,
        field_group=field_group,
        source=payload.get("source", "runtime_cache"),
        raw_value=payload.get("raw_value"),
    )


def _detect_from_business_guide(workspace_path: Path) -> CategoryDetection | None:
    guide_path = workspace_path / "business_guide.md"
    if not guide_path.exists():
        return None
    try:
        text = guide_path.read_text(encoding="utf-8")
    except Exception:
        return None
    head = "\n".join(text.splitlines()[:120])
    for pattern in _CATEGORY_PATTERNS:
        match = pattern.search(head)
        if not match:
            continue
        raw_value = match.group(1).strip()
        document_family = canonicalize_document_family(raw_value)
        document_topic = canonicalize_document_topic(raw_value)
        if document_family or document_topic:
            return _build_detection(
                document_family=document_family,
                document_topic=document_topic,
                source="business_guide_field",
                raw_value=raw_value,
            )

    document_family = canonicalize_document_family(head)
    document_topic = canonicalize_document_topic(head)
    if document_family or document_topic:
        return _build_detection(
            document_family=document_family,
            document_topic=document_topic,
            source="business_guide_keywords",
            raw_value=None,
        )
    return None


def _detect_from_schema(workspace_path: Path) -> CategoryDetection | None:
    schema_path = workspace_path / ".xdev" / "schema.json"
    if not schema_path.exists():
        return None
    try:
        payload = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    fields = set(payload.get("data", {}).keys())
    if not fields:
        return None

    best_family = None
    best_family_score = 0.0
    for category, signature in _SCHEMA_FAMILY_SIGNATURES.items():
        overlap = len(fields & signature)
        if overlap == 0:
            continue
        score = overlap / max(len(signature), 1)
        if score > best_family_score:
            best_family_score = score
            best_family = category

    best_topic = None
    best_topic_score = 0.0
    for topic, signature in _SCHEMA_TOPIC_SIGNATURES.items():
        overlap = len(fields & signature)
        if overlap == 0:
            continue
        score = overlap / max(len(signature), 1)
        if score > best_topic_score:
            best_topic_score = score
            best_topic = topic

    if best_family or best_topic:
        family = best_family or _TOPIC_DEFINITIONS.get(best_topic or "", {}).get("family")
        if best_family_score >= 0.5 or best_topic_score >= 0.5:
            return _build_detection(
                document_family=family,
                document_topic=best_topic,
                source="schema_signature",
                raw_value=",".join(sorted(fields)),
            )
    return None


def _detect_from_workspace_name(workspace_path: Path) -> CategoryDetection | None:
    workspace_name = workspace_path.name
    document_family = canonicalize_document_family(workspace_name)
    document_topic = canonicalize_document_topic(workspace_name)
    if document_family or document_topic:
        return _build_detection(
            document_family=document_family,
            document_topic=document_topic,
            source="workspace_name",
            raw_value=workspace_name,
        )
    return None

def _build_detection(
    *,
    document_family: str | None,
    document_topic: str | None,
    source: str,
    raw_value: str | None,
) -> CategoryDetection:
    if document_topic and not document_family:
        document_family = _TOPIC_DEFINITIONS.get(document_topic, {}).get("family")
    field_group = None
    if document_topic:
        field_group = _TOPIC_DEFINITIONS.get(document_topic, {}).get("field_group")
    return CategoryDetection(
        category=document_family,
        document_family=document_family,
        document_topic=document_topic,
        field_group=field_group,
        source=source,
        raw_value=raw_value,
    )


def _merge_detections(base: CategoryDetection | None, extra: CategoryDetection | None) -> CategoryDetection | None:
    if extra is None:
        return base
    if base is None:
        return extra
    adds_information = any(
        [
            extra.document_family and not base.document_family,
            extra.document_topic and not base.document_topic,
            extra.field_group and not base.field_group,
            extra.raw_value and not base.raw_value,
        ]
    )
    if not adds_information:
        return base
    family = base.document_family or extra.document_family
    topic = base.document_topic or extra.document_topic
    raw_value = base.raw_value or extra.raw_value
    sources = [part for part in [base.source, extra.source] if part]
    merged_source = "+".join(dict.fromkeys(sources))
    return _build_detection(
        document_family=family,
        document_topic=topic,
        source=merged_source,
        raw_value=raw_value,
    )


def infer_document_category(
    workspace_path: Path,
    explicit: str | None = None,
    *,
    runtime_root: Path | None = None,
) -> str | None:
    """Infer document category from explicit config, runtime cache, guide, schema, or workspace name."""
    return detect_document_category(workspace_path, explicit=explicit, runtime_root=runtime_root).category


def detect_document_category(
    workspace_path: Path,
    explicit: str | None = None,
    *,
    runtime_root: Path | None = None,
    explicit_family: str | None = None,
    explicit_topic: str | None = None,
) -> CategoryDetection:
    """Return category plus where the detection came from."""
    detection: CategoryDetection | None = None
    if explicit_topic and explicit_topic.strip():
        detection = _build_detection(
            document_family=canonicalize_document_family(explicit_family or explicit, allow_unknown=True),
            document_topic=canonicalize_document_topic(explicit_topic.strip()),
            source="explicit_topic",
            raw_value=explicit_topic.strip(),
        )
    elif explicit_family and explicit_family.strip():
        detection = _build_detection(
            document_family=canonicalize_document_family(explicit_family.strip(), allow_unknown=True),
            document_topic=canonicalize_document_topic(explicit),
            source="explicit_family",
            raw_value=explicit_family.strip(),
        )
    elif explicit and explicit.strip():
        detection = _build_detection(
            document_family=canonicalize_document_family(explicit.strip(), allow_unknown=True),
            document_topic=canonicalize_document_topic(explicit.strip()),
            source="explicit",
            raw_value=explicit.strip(),
        )

    if runtime_root is not None:
        cached = _detect_from_runtime_cache(runtime_root)
        detection = _merge_detections(detection, cached)

    for detector in (
        _detect_from_business_guide,
        _detect_from_schema,
        _detect_from_workspace_name,
    ):
        detection = _merge_detections(detection, detector(workspace_path))
    return detection or CategoryDetection(
        category=None,
        document_family=None,
        document_topic=None,
        field_group=None,
        source="unknown",
        raw_value=None,
    )


def write_category_detection(runtime_root: Path, detection: CategoryDetection) -> None:
    """Persist category detection inside runtime memory dir for stable reuse."""
    runtime_root.mkdir(parents=True, exist_ok=True)
    cache_path = runtime_root / "document_category.json"
    cache_path.write_text(
        json.dumps(asdict(detection), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def find_repo_root(start: Path) -> Path:
    """Find the outer project repo root, not the nested workspace git root."""
    current = start.resolve()

    pyproject_match: Path | None = None
    git_matches: list[Path] = []
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            pyproject_match = candidate
            break
        if (candidate / ".git").exists():
            git_matches.append(candidate)

    if pyproject_match is not None:
        return pyproject_match
    if git_matches:
        return git_matches[-1]
    return current.parents[-1] if current.parents else current


def resolve_shared_memory_root(workspace_path: Path, configured_root: str | None) -> Path:
    """Resolve the root directory used for shared category memory."""
    if configured_root:
        return Path(configured_root).expanduser().resolve()
    repo_root = find_repo_root(workspace_path)
    return repo_root / "local" / "memory_pool"
