"""工具注册表：收集所有 @tool 注册的工具，提供 OpenAI tools 协议的 schema"""
import json

from app.paths import WORKSPACE_DIR

# 注册表：name -> {name, group, label, description, parameters, readonly, needs_context, func}
TOOL_REGISTRY = {}


def tool(group: str, name: str, label: str, description: str, parameters: dict, readonly: bool,
         needs_context: bool = False):
    """工具注册装饰器

    needs_context=True 时，执行时会向工具函数额外传入 ctx 参数
    （该参数不暴露给 LLM）。
    """
    def deco(fn):
        TOOL_REGISTRY[name] = {
            "name": name,
            "group": group,
            "label": label,
            "description": description,
            "parameters": parameters,
            "readonly": readonly,
            "needs_context": needs_context,
            "func": fn,
        }
        return fn
    return deco


def get_tool(name: str):
    return TOOL_REGISTRY.get(name)


def get_tool_defs(groups=None) -> list:
    """返回 OpenAI function calling 的 tools 数组

    groups 为 None/空 -> 返回全部工具（扁平工具池，LLM 自主编排）；
    也可传空格分隔的组名做子集。
    """
    if groups:
        group_set = set(groups.split())
        tools = [t for t in TOOL_REGISTRY.values() if t["group"] in group_set]
    else:
        tools = list(TOOL_REGISTRY.values())
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in tools
    ]


def summarize_call(name: str, args: dict) -> str:
    """生成给用户确认用的中文摘要"""
    t = TOOL_REGISTRY.get(name)
    label = t["label"] if t else name
    detail = ""
    if args:
        parts = [f"{k}={v}" for k, v in list(args.items())[:3]]
        detail = ", ".join(parts)
        if len(detail) > 60:
            detail = detail[:60] + "…"
    return f"{label}（{detail}）" if detail else label


def tool_result_json(data) -> str:
    """工具执行结果序列化（回传给 LLM）"""
    return json.dumps(data, ensure_ascii=False, default=str)
