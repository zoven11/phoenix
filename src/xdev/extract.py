"""
xdev 提取执行入口
"""

from pathlib import Path
from typing import Any


async def extract_from_docjson(
    docjson: dict,
    *,
    program: str | None = None,
    workspace: str | Path | None = None,
    config: dict | None = None,
    pdf_bytes: bytes | None = None,
    include_sources: bool = False,
) -> Any:
    """从 docjson 执行提取

    三种输入方式互斥：
    - program: 程序代码字符串
    - workspace: workspace 目录路径
    - config: 旧格式配置字典

    Args:
        include_sources: 为 True 时返回 {"data": result, "sources": ...}，
            sources 按字段路径映射到页码、节点、行文本和 bbox。默认 False，
            保持原有返回结构不变。

    Raises:
        ValueError: 当输入参数不合法时
    """
    from code_executor.executor import execute
    from code_executor.provenance import locate_result_sources_from_docjson

    provided = sum(x is not None for x in [program, workspace, config])
    if provided == 0:
        raise ValueError("必须提供 program、workspace 或 config 之一")
    if provided > 1:
        raise ValueError("program、workspace、config 互斥，不能同时提供")

    from .setup import prepare_extraction_runtime

    runtime = prepare_extraction_runtime()

    if config is not None:
        raise ValueError(
            "config/flat 旧格式已不再支持。请改用 workspace/program，并让 "
            "`extract(document: Document)` 或 "
            "`extract(document: Document, tool_hub: ToolHub)` 返回完整结果。"
        )

    result = None
    if workspace is not None:
        result = await execute(
            workspace=workspace,
            docjson=docjson,
            pdf_bytes=pdf_bytes,
            tool_hub=runtime.tool_hub,
        )
    elif program is not None:
        result = await execute(
            program=program,
            docjson=docjson,
            pdf_bytes=pdf_bytes,
            tool_hub=runtime.tool_hub,
        )

    if result is not None:
        if include_sources:
            return {
                "data": result,
                "sources": locate_result_sources_from_docjson(result, docjson),
            }
        return result
    raise ValueError("必须提供 program、workspace 或 config 之一")
