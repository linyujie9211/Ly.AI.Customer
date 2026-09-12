"""工具注册模块：@tool 装饰器与 OpenAI function calling schema"""
from app.tools.registry import (  # noqa: F401
    TOOL_REGISTRY, tool, get_tool, get_tool_defs, summarize_call, tool_result_json,
)
