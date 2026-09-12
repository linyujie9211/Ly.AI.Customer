"""内置插件：知识库检索工具（把 app.knowledge.search_knowledge 包装为智能体工具）"""
from app.tools.registry import tool, tool_result_json


@tool(group="knowledge", name="kb_search", label="知识库检索",
      description="在客服知识库中检索与查询词相关的资料片段。当用户明确要求查询知识库/文档/资料，"
                  "或回答需要知识库依据时调用。",
      parameters={
          "type": "object",
          "properties": {
              "query": {"type": "string", "description": "检索关键词或问题"},
              "top_k": {"type": "integer", "description": "返回条数，默认5，最大10"},
          },
          "required": ["query"],
      },
      readonly=True)
def kb_search(query: str, top_k: int = 5):
    try:
        from app.knowledge import search_knowledge
        k = int(top_k or 5)
        hits = search_knowledge(query, top_k=max(1, min(k, 10)))
        if not hits:
            return tool_result_json(
                {"ok": True, "message": "知识库中没有找到相关内容", "hits": []})
        return tool_result_json({"ok": True, "count": len(hits), "hits": hits})
    except Exception as e:
        return tool_result_json({"ok": False, "error": str(e)})
