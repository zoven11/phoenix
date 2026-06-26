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
    if document_family == "research_report" or document_category == "research_report_universal":
        company_header_fields = {
            "公司名称",
            "股票代码",
            "investment_rating",
            "投资评级",
            "rating_action",
            "报告日期",
            "publish_date",
            "分析师",
            "analysts",
            "analyst_certificates",
            "publisher",
            "report_title",
            "report_subtitle",
            "report_type",
            "covered_subjects",
            "stock_codes",
            "industry",
        }
        financial_fields = {
            "营业收入",
            "归母净利润",
            "financial_forecasts",
            "valuation_metrics",
            "important_numbers",
        }
        target_price_fields = {"目标价", "target_price", "current_price", "market_cap"}
        viewpoint_fields = {
            "key_event",
            "核心观点",
            "core_viewpoints",
            "investment_recommendations",
            "recommended_targets",
            "catalysts",
            "summary",
            "topic_sections",
            "market_index_snapshot",
            "mentioned_companies",
            "mentioned_industries",
        }
        risk_fields = {"风险提示", "risk_warnings"}
        energy_storage_fields = {
            "储能逆变器收入_亿元",
            "储能电池包收入_亿元",
            "储能逆变器同比",
            "储能电池包同比",
        }

        if field_name in company_header_fields:
            return {
                "section_hint": "首页封面；报告标题区；分析师信息块",
                "position_hint": "通常在第一页顶部到中部。公司研究常见顺序为公司名称（股票代码）、报告标题、评级、报告日期、分析师；行业/策略报告优先取首页报告头部日期和标题附近信息。",
                "anchor_keywords": [
                    "证券研究报告",
                    "公司研究",
                    "行业研究",
                    "策略研究",
                    "买入",
                    "增持",
                    "优于大市",
                    "证券分析师",
                    "执业证书",
                ],
                "canonical_examples": ["德业股份（605117）", "买入（维持）", "证券分析师 曾朵红"],
                "normalization_rule": "股票代码去括号和交易所后缀；投资评级去掉“维持/首次”等动作，只保留评级本体；报告日期统一为YYYY年MM月DD日；分析师姓名去掉职称、证书编号和邮箱，多人用顿号分隔。",
                "layout_pattern": "首页封面字段密集，相关研究列表和历史日期可能干扰报告日期；优先标题附近或报告头部日期，不取相关研究历史日期。",
                "recommended_action": "先切首页前80行定位标题区和分析师块；公司/代码用标题或公司名括号模式，报告日期优先标题附近最新发布日期，分析师从“证券分析师/执业证书”块抽取。",
            }

        if field_name in financial_fields:
            return {
                "section_hint": "投资要点；事件点评；盈利预测与估值表；核心财务数据表",
                "position_hint": "公司研究通常在首页“投资要点”第一条事件或正文财务摘要中；行业/策略报告通常无单公司财务数据，应按缺失规则返回null或空列表。",
                "anchor_keywords": [
                    "投资要点",
                    "事件",
                    "营业收入",
                    "归母净利润",
                    "同比",
                    "盈利预测",
                    "估值",
                ],
                "canonical_examples": ["公司25年营收122.2亿元", "归母净利润31.7亿元"],
                "normalization_rule": "营业收入和归母净利润统一为亿元float；列表型预测/估值保留年份、指标和值；行业/策略报告没有明确单公司财务值时返回null或空列表。",
                "layout_pattern": "财务数字常与年份和同比混排，优先取最新报告期或报告明确强调的报告期；不要把同比百分比或目标价误当金额。",
                "recommended_action": "定位“投资要点/事件/盈利预测”附近句子和财务表，按字段名锚点提取同句或同表行数值，并统一单位为亿元。",
            }

        if field_name in target_price_fields:
            return {
                "section_hint": "盈利预测及投资评级；估值分析；首页评级摘要",
                "position_hint": "通常在投资要点末段或“盈利预测及投资评级”小节，可能紧邻维持买入/增持评级。",
                "anchor_keywords": ["目标价", "合理价值", "盈利预测", "投资评级", "估值", "PE", "PB"],
                "canonical_examples": ["给予目标价163元", "对应目标价163元/股"],
                "normalization_rule": "目标价提取数值float，不保留元/港元单位后缀；无明确目标价返回null；不要把当前价、市值或估值倍数误作目标价。",
                "layout_pattern": "目标价常在正文评级段落，不一定在首页表格；需要排除股票代码、日期、PE倍数等相邻数字。",
                "recommended_action": "优先扫描“目标价/合理价值”锚点所在句，再回退“盈利预测及投资评级”小节；只取价格单位附近的数字。",
            }

        if field_name in viewpoint_fields:
            return {
                "section_hint": "投资要点；核心观点；报告摘要；行业/策略正文小标题",
                "position_hint": "多在首页摘要区或正文首屏项目符号；策略/行业报告重点看标题后的摘要和小标题序列。",
                "anchor_keywords": ["投资要点", "核心观点", "事件", "投资建议", "推荐", "催化", "摘要"],
                "canonical_examples": ["事件：公司25年营收...", "核心观点：..."],
                "normalization_rule": "保留观点的业务含义和顺序，去掉免责声明、页眉页脚和目录噪声；列表字段按要点拆分。",
                "layout_pattern": "观点常为项目符号或短段落，和风险提示/免责声明相邻时要截断到观点段落边界。",
                "recommended_action": "先定位首页“投资要点/核心观点/摘要”段，按项目符号或小标题切分；行业/策略报告可从正文一级小标题补充主题章节。",
            }

        if field_name in risk_fields:
            return {
                "section_hint": "风险提示；投资要点末尾风险段；正文末尾风险提示",
                "position_hint": "常在首页投资要点最后一条或正文最后一节，策略研究可能是免责声明前连续多句风险段。",
                "anchor_keywords": ["风险提示", "风险因素", "不及预期", "竞争加剧", "国际政治经济风险"],
                "canonical_examples": ["竞争加剧、需求不及预期", "产能扩张不及预期、下游品牌销售疲软"],
                "normalization_rule": "去掉“风险提示：”前缀，保留核心风险要点；策略/行业报告可保留连续多句风险，不要截到第一个句号就结束。",
                "layout_pattern": "风险段常紧邻正文末尾免责声明，需要在免责声明/评级说明前截断。",
                "recommended_action": "优先搜索“风险提示”标题，取其后到免责声明、评级说明或下一大标题前的内容；无标题时取投资要点末尾风险句。",
            }

        if field_name in energy_storage_fields:
            return {
                "section_hint": "投资要点；业务拆分段；储能业务点评",
                "position_hint": "通常在公司研究首页“投资要点”内的业务拆分句，常见于“储能逆变器/电池包同比高增”相关项目符号。",
                "anchor_keywords": ["储能逆变器", "储能电池包", "电池包", "收入", "同比", "工商储"],
                "canonical_examples": ["储能逆变器收入52.2亿元，同比+18.9%", "电池包收入38.3亿元，同比+56.3%"],
                "normalization_rule": "收入字段统一为亿元float；同比字段保留原文百分比字符串和正负号；非储能报告收入返回null、同比返回空字符串。",
                "layout_pattern": "同一句中可能同时出现逆变器和电池包两组收入/同比，必须按业务名就近绑定，避免串列。",
                "recommended_action": "定位含“储能逆变器/电池包”的业务拆分句，按业务关键词就近抽收入和同比；没有对应业务锚点时按缺失规则填充。",
            }

        return {
            "section_hint": "首页摘要；投资要点；正文相关小节",
            "position_hint": "证券研报字段优先从首页标题区、摘要区、投资要点和正文同名小节提取；页眉页脚、免责声明和相关研究列表仅作排除。",
            "anchor_keywords": [field_name, "投资要点", "核心观点", "风险提示"],
            "canonical_examples": [],
            "normalization_rule": "按 schema 类型返回；缺失文本返回空字符串或空列表，缺失数值返回null。",
            "layout_pattern": "研报首页信息密集，需先分离封面/摘要/分析师块，再进入正文小节。",
        }

    if document_family == "annual_report" or document_category == "annual_report":
        share_capital_fields = {
            "总股本",
            "已流通股份",
            "人民币普通股",
            "流通受限股份",
            "其他流通受限股份",
            "其中：境内自然人持股",
            "其他内资持股（受限）",
            "控股股东、实际控制人",
        }
        dividend_fields = {
            "转增比例 (10: X)",
            "送股比例 (10: X)",
            "派息比例[人民币] (10: X)",
        }
        shareholder_count_fields = {"A 股户数", "股东总户数"}
        audit_fields = {
            "is_audited",
            "domestic_audit_opinion_type",
            "domestic_signing_cpas",
            "domestic_audit_firm_name",
        }

        if field_name in share_capital_fields:
            examples = ["总股本 327,304,000", "有限售条件股份 86,620,670"]
            if field_name in {"其中：境内自然人持股", "其他内资持股（受限）"}:
                examples = ["董事、监事、高管 3,830,070；核心员工 6,370,000"]
            return {
                "section_hint": "年度报告第六节“股份变动及股东情况”",
                "position_hint": "普通股股本结构表，优先取“期末”数量列；通常位于该节开头",
                "anchor_keywords": [
                    "普通股股本结构",
                    "有限售条件股份",
                    "无限售条件股份",
                    "总股本",
                    "董事、监事、高管",
                ],
                "canonical_examples": examples,
                "normalization_rule": (
                    "股份数量保留原文千分位字符串；表格中的‘-’按0处理。"
                    "总股本=无限售条件股份+有限售条件股份；已流通股份=无限售条件股份总数；"
                    "人民币普通股通常与已流通股份相同。境内自然人持股和其他内资持股（受限）"
                    "优先取明细行；无明细行时可用董事、监事、高管+核心员工，但必须校验"
                    "董监高+核心员工+控股股东是否不超过有限售股份总数，存在重叠时回退为0。"
                ),
                "layout_pattern": (
                    "股本结构表常为12-14行、期初/本期变动/期末三组列。必须按行标题和"
                    "期末数量列定位，避免抽期初、比例列或本期变动列；全流通或无受限股份时"
                    "受限相关字段按通用schema填字符串0。"
                ),
                "recommended_action": (
                    "先定位第六节普通股股本结构表，解析期末数量列。境内自然人持股和其他内资持股"
                    "先找明细行；无明细时计算董监高+核心员工，并校验董监高+核心员工+控股股东"
                    "<=有限售股份总数，否则填字符串0。"
                ),
            }

        if field_name in shareholder_count_fields:
            return {
                "section_hint": "年度报告第六节“股份变动及股东情况”",
                "position_hint": "普通股股本结构或股东情况表附近，常在表格最后一行、倒数第二行或前十名股东表之前",
                "anchor_keywords": [
                    "截至报告期末普通股股东总数",
                    "普通股股东人数",
                    "普通股股东总数",
                    "股东总数",
                ],
                "canonical_examples": ["截至报告期末普通股股东总数(户) 10,675"],
                "normalization_rule": (
                    "提取纯数字，去除千分位逗号、中文逗号并转整数；无法提取时返回null。"
                    "仅有A股/普通股时，A股户数可与股东总户数相同；A股户数不应大于股东总户数。"
                ),
                "layout_pattern": (
                    "两列表格或跨列单元格，行标题包含普通股股东人数/普通股股东总数/"
                    "截至报告期末普通股股东总数。优先从普通股股本结构表或股东总数表取报告期末值，"
                    "不要误抽年度报告披露日前上一月末户数。"
                ),
                "recommended_action": (
                    "筛选包含普通股股东人数/普通股股东总数的表，优先取“截至报告期末”行；"
                    "不要取“年度报告披露日前上一月末”户数。若行内多个数字，选择报告期末口径对应单元格或第一个合理户数。"
                ),
            }

        if field_name in dividend_fields:
            return {
                "section_hint": "权益分派情况；利润分配或资本公积金转增股本预案；年度分配预案",
                "position_hint": "通常位于董事会报告、重要事项或权益分派情况章节，优先取本报告期年度分配预案行",
                "anchor_keywords": [
                    "年度分配预案",
                    "每10股派现数",
                    "每10股派息数",
                    "每10股送股数",
                    "每10股转增数",
                ],
                "canonical_examples": ["年度分配预案 每10股派现数（含税）0.90"],
                "normalization_rule": (
                    "统一返回每10股对应X值；空值、‘-’、不适用归一为0；有小数时保留原文精度。"
                    "派息、送股、转增三个字段必须来自同一个分红方案，不能混用不同方案的列值。"
                ),
                "layout_pattern": (
                    "先收集所有分红方案并判断状态：报告期内已实施分红优先，其次报告期后已实施方案，"
                    "无已实施方案时再取年度分配预案。表格型方案先匹配表头列（派现/派息、送股、转增），"
                    "再匹配年度分配预案/权益分派方案行按列取值；文字型方案用每10股派现/送股/转增锚点回退。"
                ),
                "recommended_action": (
                    "列出候选分红方案及状态，按报告期内已实施>报告期后已实施>年度预案选一个方案；"
                    "从同一方案中同时抽派息、送股、转增，保留原文小数格式。"
                ),
            }

        if field_name in audit_fields:
            return {
                "section_hint": "重要提示；审计报告；聘任、解聘会计师事务所情况",
                "position_hint": "审计意见常在年报前部重要提示或审计报告正文，签字注册会计师通常在审计报告末尾签章处",
                "anchor_keywords": ["审计报告", "标准无保留意见", "中国注册会计师：", "会计师事务所"],
                "canonical_examples": ["中国注册会计师：李莉", "标准无保留意见"],
                "normalization_rule": "审计意见保留财务报表审计意见原文；签字注册会计师返回姓名列表并去重。",
                "layout_pattern": "优先摘要表；缺失时扫描重要提示和审计报告末尾签章区域。",
            }

        if field_name == "主要财务指标":
            return {
                "section_hint": "公司简介和主要财务指标；主要会计数据和财务指标；财务概览",
                "position_hint": "通常位于年报前部第二节，少数金融机构在前部财务概览表",
                "anchor_keywords": ["主要财务指标", "基本每股收益", "稀释每股收益", "加权平均净资产收益率"],
                "canonical_examples": ["基本每股收益（元／股） 1.00 0.68"],
                "normalization_rule": "逐行保留项目原文、本期金额、上期金额；不要把同比增减列作为上期金额。",
                "layout_pattern": "首列为项目，后续列为本期年度、上期年度、同比增减、更早年度。",
            }

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
                recommended_action=str(
                    location.get("recommended_action")
                    or (
                        f"Before broad repair, inspect field `{field_name}` on failing docs ({docs}) "
                        "with `xdev run <doc_id>` and constrain the fix to this field first."
                    )
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


def build_success_field_candidates(
    *,
    run_id: str,
    evidence: list[EvolutionMemoryEvidence],
    document_category: str | None = None,
    document_family: str | None = None,
    document_topic: str | None = None,
    field_group: str | None = None,
) -> list[EvolutionMemoryCandidate]:
    """Build field-location memories after a validated successful run.

    Evidence currently stores failing fields rather than the full schema.  For
    document families with stable universal schemas, emit a conservative set of
    reusable field-location memories when the run reaches full accuracy.
    """
    latest_eval = _latest_evaluation(evidence)
    if latest_eval is None or latest_eval.accuracy is None or latest_eval.accuracy < 1.0:
        return []

    is_research_report = (
        document_family == "research_report"
        or document_category == "research_report_universal"
        or document_topic == "universal_research_report"
    )
    if not is_research_report:
        return []

    field_names = [
        "公司名称",
        "股票代码",
        "投资评级",
        "报告日期",
        "分析师",
        "营业收入",
        "归母净利润",
        "目标价",
        "风险提示",
        "储能逆变器收入_亿元",
        "储能电池包收入_亿元",
        "储能逆变器同比",
        "储能电池包同比",
    ]
    doc_count = latest_eval.doc_count or "unknown"
    accuracy_text = f"{latest_eval.accuracy:.1%}"
    field_avg_text = (
        f"{latest_eval.field_average:.1%}" if latest_eval.field_average is not None else "unknown"
    )
    candidates: list[EvolutionMemoryCandidate] = []
    for field_name in field_names:
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
                title=f"Successful field location pattern: {field_name}",
                scope="workspace",
                memory_type="strategy",
                field_name=field_name,
                category="successful_field_location",
                document_category=document_category,
                document_family=document_family or document_category,
                document_topic=document_topic,
                field_group=field_group,
                failure_category=None,
                section_hint=location["section_hint"],
                position_hint=location["position_hint"],
                anchor_keywords=list(location["anchor_keywords"]),
                canonical_examples=list(location["canonical_examples"]),
                normalization_rule=location["normalization_rule"],
                layout_pattern=location["layout_pattern"],
                problem_pattern=(
                    f"Successful research-report extraction reached {accuracy_text} "
                    f"on {doc_count} docs; preserve the validated location strategy for `{field_name}`."
                ),
                applicable_conditions=_base_applicable_conditions(
                    document_category=document_category,
                    document_family=document_family,
                    document_topic=document_topic,
                ),
                recommended_action=str(location.get("recommended_action") or ""),
                forbidden_action=(
                    "Do not replace this field-specific location strategy with broad full-text guessing "
                    "unless evaluation evidence shows the pattern no longer applies."
                ),
                evidence_refs=[
                    f"field_name={field_name}",
                    f"validated_accuracy={accuracy_text}",
                    f"field_average={field_avg_text}",
                    f"doc_count={doc_count}",
                ],
                source_evidence_ids=[latest_eval.id],
            )
        )
    return candidates
