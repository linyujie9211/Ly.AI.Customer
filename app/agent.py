"""智能客服对话：模型加载 + RAG 注入 + 插件知识包路由 + function calling 工具循环

插件知识包 = 启用插件的 skill.md（workspace/plugins/，内置与用户插件同源），
只提供领域知识（提示词），不限制可用工具；所有工具（含内置插件的）
由 plugin_manager 动态加载注册后全局可见，LLM 在循环中自主编排调用顺序。
"""
import json
import re
import urllib.request
import urllib.error
from pathlib import Path

from app.storage import ModelStorage
from app.logger import logger


storage = ModelStorage()

# 智能客服系统提示词
SYSTEM_PROMPT = (
    "你是一名专业的智能客服助手。请用友好、简洁、准确的语言回答用户的问题。"
    "如果用户的问题超出你的知识范围，请如实说明并引导用户补充更多信息。"
)

# 知识库检索注入模板
KB_PROMPT_TEMPLATE = (
    "以下是知识库中与用户问题相关的资料：\n"
    "{context}\n"
    "请优先依据以上资料回答用户问题；资料中没有的内容按你自己的知识回答，并如实说明。"
)


def retrieve_knowledge(user_query: str):
    """检索知识库相关内容，异常时返回 None（不阻断对话）"""
    try:
        from app.knowledge import search_knowledge
        return search_knowledge(user_query, top_k=5)
    except Exception as e:
        logger.warning("知识库检索失败（跳过 RAG）: %s", e)
        return None


def load_model(model_id):
    """加载模型配置，不存在或未启用则抛错"""
    m = storage.get_model(model_id)
    if not m:
        raise ValueError(f"模型不存在: id={model_id}")
    if not m.get("enabled"):
        raise ValueError(f"模型已禁用: {m.get('name')}")
    if not m.get("base_url"):
        raise ValueError(f"模型未配置请求地址: {m.get('name')}")
    return m


# ---------- 插件知识包 ----------

def _parse_skill_file(path: Path) -> dict:
    """解析技能文件：front matter（name/description）+ 提示词正文"""
    text = path.read_text(encoding="utf-8")
    meta = {}
    body = text.strip()
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip().strip("\"'")
            body = parts[2].strip()
    return {
        "name": meta.get("name") or path.stem,
        "description": meta.get("description", ""),
        "prompt": body,
    }


def list_skills() -> list:
    """扫描知识包（每次调用重新读取，新增/修改插件无需重启）

    来源：启用插件的 skill.md（workspace/plugins/*/，内置插件与用户插件同源）。
    """
    try:
        from app.plugin_manager import list_enabled_skills  # 延迟导入避免循环依赖
        return list_enabled_skills()
    except Exception as e:
        logger.warning("插件知识包加载失败: %s", e)
        return []


def get_skill(name: str):
    """按名称取技能，不存在返回 None"""
    name = (name or "").lower()
    for s in list_skills():
        if s["name"].lower() == name:
            return s
    return None


def route_knowledge_packs(model, user_query, history=None) -> list:
    """LLM 知识包路由：根据用户输入判断需要注入哪些领域知识（可多选）

    知识包 = 插件的 skill.md，不作为工具边界；工具池全局可见，
    LLM 在循环中自主编排调用顺序。返回 [] 表示无需领域知识（纯通用对话）。
    """
    skills = list_skills()
    if not skills:
        return []
    lines = [
        "你是任务规划器。根据用户的最新输入和对话历史，判断完成本次任务需要哪些领域知识包（可多个）。",
        "",
        "可用知识包：",
    ]
    for s in skills:
        lines.append(f"- {s['name']}: {s['description']}")
    lines += [
        "",
        "规则：",
        "- 只输出知识包名，多个用空格分隔；不需要任何领域知识（普通咨询、闲聊等）时输出 none",
        "- 只输出一行，不要解释",
    ]

    messages = [{"role": "system", "content": "\n".join(lines)}]
    # 压缩历史辅助路由（最近4条，每条截断200字符）
    for m in (history or [])[-4:]:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            content = m["content"]
            if len(content) > 200:
                content = content[:200] + "…(已截断)"
            messages.append({"role": m["role"], "content": content})
    messages.append({"role": "user", "content": user_query.strip()})

    try:
        answer = openai_chat_completion_msg(
            base_url=model.get("base_url", ""),
            api_key=model.get("api_key", ""),
            model_id=model.get("model_id", ""),
            messages=messages,
            timeout=15,
        ).get("content") or ""
    except Exception as e:
        logger.warning("知识包路由调用失败，回退通用对话: %s", e)
        return []

    valid = {s["name"].lower(): s["name"] for s in skills}
    packs = []
    for token in re.split(r"[\s,，]+", answer.strip().strip("`'\"。.")):
        token = token.strip().lower()
        if token in valid and valid[token] not in packs:
            packs.append(valid[token])
        elif token != "none" and token:
            # 包含匹配兜底
            for full, orig in valid.items():
                if full in token and orig not in packs:
                    packs.append(orig)
                    break
    return packs


# ---------- LLM 基础调用 ----------

def openai_chat_completion_msg(base_url, api_key, model_id, messages, timeout=30, tools=None, max_tokens=None):
    """调用 OpenAI 兼容 /chat/completions，返回完整的 assistant message

    支持 function calling：传入 tools 时返回值可能带 tool_calls。

    Returns:
        dict: {"role":"assistant","content":str|None,"tool_calls":[...]|None}
    """
    url = (base_url or "").rstrip("/") + "/chat/completions"
    payload = {
        "model": model_id,
        "messages": messages,
        "temperature": 0,
        "stream": False,
    }
    if max_tokens:
        payload["max_tokens"] = int(max_tokens)
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    logger.info("LLM 请求 url=%s model=%s tools=%s", url, model_id, bool(tools))
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        choice = data["choices"][0]
        _check_truncation(choice.get("finish_reason"), choice.get("message", {}).get("tool_calls"))
        msg = choice["message"]
        return {
            "role": "assistant",
            "content": (msg.get("content") or "").strip(),
            "tool_calls": msg.get("tool_calls"),
        }
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        logger.error("LLM 调用 HTTP 错误 %s: %s", e.code, err_body)
        raise RuntimeError(f"模型调用失败(HTTP {e.code}): {err_body or str(e)}")
    except RuntimeError:
        # 截断等已明确记录过日志的错误，原样抛出
        raise
    except Exception as e:
        logger.error("LLM 调用异常: %s", e, exc_info=True)
        raise RuntimeError(f"模型调用异常: {e}")


def _check_truncation(finish_reason, tool_calls=None):
    """检测 LLM 输出是否因达到 max_tokens 被截断（finish_reason=length）"""
    if finish_reason != "length":
        return
    if tool_calls:
        logger.warning("LLM 输出达到 max_tokens 上限被截断（finish_reason=length），工具参数可能不完整")
        return
    logger.warning("LLM 文本输出达到 max_tokens 上限被截断（finish_reason=length）")


def _repair_json_tail(s: str):
    """修复模型输出的残缺 JSON 参数：补齐缺失的尾部闭合括号。

    小模型经常漏掉 JSON 末尾的 ] / }（或输出被截断在结构边界），
    扫描未闭合的括号栈补齐后重新解析。仅当截断点不在字符串内部时修复。
    Returns: 修复成功返回解析后的对象；无法安全修复返回 None。
    """
    if not s or not isinstance(s, str):
        return None
    in_str = False
    escape = False
    stack = []
    for ch in s:
        if escape:
            escape = False
            continue
        if ch == "\\":
            if in_str:
                escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if not in_str:
            if ch in "([{":
                stack.append(ch)
            elif ch in ")]}":
                if stack:
                    stack.pop()
    if in_str or not stack:
        return None
    closer = {"(": ")", "[": "]", "{": "}"}
    fixed = s + "".join(closer[ch] for ch in reversed(stack))
    try:
        return json.loads(fixed)
    except Exception:
        return None


def openai_chat_completion_stream(base_url, api_key, model_id, messages, timeout=120, tools=None, max_tokens=None):
    """流式调用 OpenAI 兼容 /chat/completions（stream=True）

    逐块生成事件：
        {"type": "delta", "content": "增量文本"}
        {"type": "done",  "msg": 完整 assistant message（含聚合的 tool_calls）}

    timeout 为 socket 级读超时（相邻 chunk 间隔），不是总时长，适合长回复。
    """
    url = (base_url or "").rstrip("/") + "/chat/completions"
    payload = {
        "model": model_id,
        "messages": messages,
        "temperature": 0.7,
        "stream": True,
    }
    if max_tokens:
        payload["max_tokens"] = int(max_tokens)
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    logger.info("LLM 流式请求 url=%s model=%s tools=%s", url, model_id, bool(tools))
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    content_parts = []
    tool_calls_acc = {}  # index -> 聚合的 tool_call
    finish_reason = None

    def _handle_line(line):
        """处理一条完整 SSE 行；返回 True 表示收到 [DONE]（可能 yield delta 事件）"""
        nonlocal finish_reason
        if not line.startswith("data:"):
            return False
        data = line[5:].strip()
        if data == "[DONE]":
            return True
        try:
            chunk = json.loads(data)
        except Exception:
            logger.warning("LLM 流式响应含无法解析的 SSE 行，已跳过: %s", data[:120])
            return False
        choices = chunk.get("choices") or [{}]
        if choices[0].get("finish_reason"):
            finish_reason = choices[0]["finish_reason"]
        delta = choices[0].get("delta") or {}
        c = delta.get("content")
        if c:
            content_parts.append(c)
            yield {"type": "delta", "content": c}
        for tc in delta.get("tool_calls") or []:
            idx = tc.get("index", 0)
            acc = tool_calls_acc.setdefault(
                idx, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            if tc.get("id"):
                acc["id"] = tc["id"]
            fn = tc.get("function") or {}
            if fn.get("name"):
                acc["function"]["name"] += fn["name"]
            if fn.get("arguments"):
                acc["function"]["arguments"] += fn["arguments"]
        return False

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # 严格按换行分帧：网络分片可能在任意字节处切断 SSE 行，
            # 未见到换行的残段必须留在缓冲等下一段
            buf = b""
            done = False
            while not done:
                raw = resp.read1(65536) if hasattr(resp, "read1") else resp.read(65536)
                if not raw:
                    break
                buf += raw
                while True:
                    nl = buf.find(b"\n")
                    if nl < 0:
                        break
                    line_bytes, buf = buf[:nl], buf[nl + 1:]
                    if (yield from _handle_line(line_bytes.decode("utf-8", errors="ignore").strip())):
                        done = True
                        break
            # 流结束后缓冲里的残留行：可能是无换行结尾的最后一条 data 行，不能丢
            if not done and buf.strip():
                tail = buf.decode("utf-8", errors="ignore").strip()
                buf = b""
                if (yield from _handle_line(tail)):
                    done = True
            if buf.strip():
                logger.warning("LLM 流式响应结尾存在无法处理的残留: %s",
                               buf.decode("utf-8", errors="ignore")[:120])
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        logger.error("LLM 流式调用 HTTP 错误 %s: %s", e.code, err_body)
        raise RuntimeError(f"模型调用失败(HTTP {e.code}): {err_body or str(e)}")
    except Exception as e:
        logger.error("LLM 流式调用异常: %s", e, exc_info=True)
        raise RuntimeError(f"模型调用异常: {e}")

    tool_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc)] if tool_calls_acc else None
    _check_truncation(finish_reason, tool_calls)
    yield {
        "type": "done",
        "msg": {
            "role": "assistant",
            "content": ("".join(content_parts)).strip() or None,
            "tool_calls": tool_calls,
        },
    }


# ---------- 工具循环（function calling） ----------

MAX_TOOL_ROUNDS = 5  # 只读工具最多连续执行轮数，防止死循环


def _exec_tool_call(name, args_json, ctx=None):
    """执行单个工具调用

    needs_context 的工具会额外收到 ctx（后端注入的运行时上下文）。

    Returns:
        (ok: bool, payload)  payload 回传给 LLM 或展示给用户
    """
    from app.tools.registry import TOOL_REGISTRY
    t = TOOL_REGISTRY.get(name)
    if not t:
        return False, {"error": f"未知工具: {name}"}
    try:
        args = json.loads(args_json or "{}")
    except Exception:
        return False, {"error": "工具参数不是合法 JSON"}
    if not isinstance(args, dict):
        return False, {"error": f"工具参数不是合法对象: {args!r}"}
    try:
        # 按工具 schema 白名单过滤参数：模型可能幻觉出 schema 外的多余参数，直接丢弃
        props = (t.get("parameters") or {}).get("properties") or {}
        if props:
            dropped = [k for k in args if k not in props]
            if dropped:
                # 参数名救援：若"恰好一个被丢弃的数组参数"对应"工具恰好一个未传的数组参数"，自动改名采用
                absent_arrays = [k for k, spec in props.items()
                                 if isinstance(spec, dict) and spec.get("type") == "array"
                                 and k not in args]
                list_dropped = [k for k in dropped if isinstance(args.get(k), list)]
                if len(absent_arrays) == 1 and len(list_dropped) == 1:
                    args[absent_arrays[0]] = args.pop(list_dropped[0])
                    logger.info("工具 %s 参数名救援: %s -> %s", name,
                                list_dropped[0], absent_arrays[0])
                    dropped = [k for k in dropped if k != list_dropped[0]]
                if dropped:
                    logger.warning("工具 %s 收到 schema 外参数，已过滤: %s", name, dropped)
                    args = {k: v for k, v in args.items() if k in props}
                    required = (t.get("parameters") or {}).get("required") or []
                    missing = [k for k in required if k not in args]
                    if missing:
                        return False, {
                            "error": f"参数 {dropped} 不是本工具支持的参数，已丢弃，"
                                     f"导致缺少必需参数 {missing}。请只使用工具定义中的参数重新调用，"
                                     f"不要自行发明参数名。"}
        if t.get("needs_context"):
            result = t["func"](**args, ctx=ctx)
        else:
            result = t["func"](**args)
        logger.info("工具执行成功 %s", name)
        return True, result
    except Exception as e:
        logger.warning("工具执行失败 %s: %s", name, e)
        return False, {"error": str(e)}


def run_tool_loop(model, system_prompt, user_query, history=None, ctx=None, emit=None):
    """扁平工具池主循环：LLM 自主编排工具调用完成任务

    所有注册工具全局可见，只读工具直接执行并回传结果，
    写工具暂停等待用户确认（execute_pending_tool 恢复）。

    Returns:
        dict: 正常结束 -> text/tool_trace；待确认 -> pending_tool + resume_messages
    """
    from app.tools.registry import get_tool_defs

    tool_defs = get_tool_defs()  # 全局工具池
    if not tool_defs:
        raise RuntimeError("未注册任何工具")

    full_prompt = (
        f"{system_prompt}\n\n"
        "【工具使用规则】\n"
        "1. 通过 function calling 调用工具完成任务，可以连续调用多个工具、自主安排顺序。\n"
        "2. 任务完成后，用中文向用户总结结果。\n"
        "3. 写操作类工具（非只读）会先暂停等待用户确认，不要重复调用。\n"
        "4. 工具返回 {\"error\": ...} 时，用中文把原因转告用户并给出可行建议。\n"
        "5. 不需要任何工具就能回答的问题，直接用中文回复。"
    )

    messages = [{"role": "system", "content": full_prompt}]
    for m in (history or [])[-6:]:
        role = m.get("role")
        content = m.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_query.strip()})

    return _continue_tool_loop(model, tool_defs, messages, [], ctx, emit=emit)


def _continue_tool_loop(model, tool_defs, messages, trace, ctx=None, emit=None):
    """工具循环主体：只读工具直接执行并回传；写工具暂停等待用户确认

    emit: 流式事件回调（可选）。传入时 LLM 调用改为流式，实时转发
          {"type":"delta","content":...} 与 {"type":"tool_start",...} 事件。
    """
    from app.tools.registry import get_tool, summarize_call, tool_result_json

    def _call_llm(msgs, use_tools):
        """按是否流式调用 LLM：emit 存在时逐块转发 delta"""
        if not emit:
            return openai_chat_completion_msg(
                base_url=model.get("base_url", ""),
                api_key=model.get("api_key", ""),
                model_id=model.get("model_id", ""),
                messages=msgs,
                tools=tool_defs if use_tools else None,
            )
        msg = None
        for ev in openai_chat_completion_stream(
                base_url=model.get("base_url", ""),
                api_key=model.get("api_key", ""),
                model_id=model.get("model_id", ""),
                messages=msgs,
                tools=tool_defs if use_tools else None):
            if ev["type"] == "delta":
                emit({"type": "delta", "content": ev["content"]})
            else:
                msg = ev["msg"]
        return msg

    for _round in range(MAX_TOOL_ROUNDS):
        msg = _call_llm(messages, True)

        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            # LLM 给出最终回复
            return {
                "text": msg.get("content") or "任务完成。",
                "executed": True,
                "tool_trace": trace,
                "model": model.get("display_name") or model.get("name") or "",
            }

        messages.append({"role": "assistant", "content": msg.get("content") or None,
                         "tool_calls": tool_calls})

        for tc in tool_calls:
            fn = (tc.get("function") or {})
            name = fn.get("name", "")
            args_json = fn.get("arguments") or "{}"
            try:
                args_for_summary = json.loads(args_json or "{}")
            except Exception as e:
                # 参数 JSON 残缺：小模型常漏掉尾部闭合括号，先尝试自动补齐修复
                repaired = _repair_json_tail(args_json)
                if isinstance(repaired, dict):
                    logger.info("工具 %s 参数 JSON 残缺，已自动补齐修复", name)
                    args_for_summary = repaired
                    args_json = json.dumps(repaired, ensure_ascii=False)
                    fn["arguments"] = args_json
                else:
                    # 无法安全修复（典型原因：模型输出被截断）。
                    # 不整体失败：把错误作为工具结果回传给 LLM，引导其重试
                    logger.warning("工具 %s 参数 JSON 不完整，已回传 LLM 引导重试: %s", name, e)
                    t_err = get_tool(name)
                    trace.append({
                        "tool": name,
                        "label": t_err["label"] if t_err else name,
                        "ok": False,
                        "summary": "参数超出模型输出上限被截断，已要求重试",
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": tool_result_json({"error": (
                            f"工具 {name} 的参数 JSON 不完整（疑似超出模型输出上限被截断）。"
                            "请缩小参数规模后重试。")}),
                    })
                    continue
            if not isinstance(args_for_summary, dict):
                args_for_summary = {}
            t = get_tool(name)
            if t and not t["readonly"]:
                # 非只读工具：暂停，等待用户确认
                return {
                    "text": None,
                    "executed": False,
                    "tool_trace": trace,
                    "pending_tool": {
                        "name": name,
                        "args": args_for_summary,
                        "summary": summarize_call(name, args_for_summary),
                        "tool_call_id": tc.get("id", ""),
                    },
                    "resume_messages": messages,
                    "model": model.get("display_name") or model.get("name") or "",
                }
            # 只读工具：立即执行
            if emit:
                emit({"type": "tool_start", "label": t["label"] if t else name,
                      "summary": summarize_call(name, args_for_summary)})
            ok, payload = _exec_tool_call(name, args_json, ctx)
            trace.append({"tool": name, "label": t["label"] if t else name,
                          "ok": ok, "summary": summarize_call(name, args_for_summary)})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": tool_result_json(payload),
            })

    # 超过轮数上限，强制让 LLM 总结
    messages.append({"role": "user", "content": "已达到工具调用轮数上限，请基于已有结果用中文总结。"})
    msg = _call_llm(messages, False)
    return {
        "text": msg.get("content") or "任务完成。",
        "executed": True,
        "tool_trace": trace,
        "model": model.get("display_name") or model.get("name") or "",
    }


def execute_pending_tool(model, pending_tool: dict, resume_messages: list, ctx=None, emit=None):
    """用户确认后：执行待确认工具，把结果回传 LLM 继续任务

    Returns:
        dict: 与 run_tool_loop 相同结构（可能是最终回复，也可能是下一个待确认工具）
    """
    from app.tools.registry import get_tool, summarize_call, tool_result_json, get_tool_defs

    name = pending_tool.get("name", "")
    args = pending_tool.get("args", {})
    tool_call_id = pending_tool.get("tool_call_id", "")

    t = get_tool(name)
    if not t:
        raise ValueError(f"未知工具: {name}")
    if not isinstance(args, dict):
        raise ValueError(f"工具参数不是合法对象: {args!r}")

    ok, payload = _exec_tool_call(name, json.dumps(args, ensure_ascii=False), ctx)
    trace = [{"tool": name, "label": t["label"], "ok": ok, "summary": summarize_call(name, args)}]

    messages = list(resume_messages or [])
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": tool_result_json(payload),
    })

    # 恢复循环（全局工具池，允许链式编排）
    return _continue_tool_loop(model, get_tool_defs(), messages, trace, ctx, emit=emit)


def run_chat(model_id, user_query, history=None, emit=None):
    """智能客服对话主流程：RAG 注入 + 插件知识包路由 + 工具循环

    Args:
        model_id: models 表主键
        user_query: 用户问题
        history: 历史消息 [{"role": "user"/"assistant", "content": ...}]
        emit: 流式事件回调，签名为 emit({"type": "delta", "content": ...})

    Returns:
        dict: {"text", "model", "tool_trace"?, "pending_tool"?, "resume_messages"?}
    """
    if not model_id or not isinstance(model_id, int) or model_id <= 0:
        raise ValueError("未选择有效的模型")
    if not user_query or not user_query.strip():
        raise ValueError("问题不能为空")

    model = load_model(model_id)

    # RAG：检索启用的知识库，将相关内容注入系统提示词（保留原有自动注入行为）
    system_prompt = SYSTEM_PROMPT
    kb_hits = retrieve_knowledge(user_query)
    if kb_hits:
        context = "\n\n".join(
            f"【{h['kb']} · {h['doc']}】\n{h['content']}" for h in kb_hits
        )
        system_prompt = SYSTEM_PROMPT + "\n\n" + KB_PROMPT_TEMPLATE.format(context=context)

    # 插件知识包路由：无启用插件知识包时自动跳过（不影响原有对话）
    try:
        packs = route_knowledge_packs(model, user_query, history)
        logger.info("知识包路由 -> %s", packs or "无（通用对话）")
    except Exception as e:
        logger.warning("知识包路由异常，跳过: %s", e)
        packs = []
    for name in packs:
        sk = get_skill(name)
        if sk and sk.get("prompt"):
            system_prompt += f"\n\n==== {name} 领域知识 ====\n{sk['prompt']}"

    # 有注册工具时走 function calling 工具循环；否则纯流式对话（保持原有行为）
    from app.tools.registry import get_tool_defs
    if get_tool_defs():
        return run_tool_loop(model, system_prompt, user_query, history, emit=emit)

    messages = [{"role": "system", "content": system_prompt}]
    for m in (history or []):
        if m.get("role") in ("user", "assistant") and m.get("content"):
            content = m["content"]
            if len(content) > 4000:
                content = content[:4000] + "…(已截断)"
            messages.append({"role": m["role"], "content": content})
    messages.append({"role": "user", "content": user_query.strip()})

    text = ""
    for ev in openai_chat_completion_stream(
        base_url=model.get("base_url", ""),
        api_key=model.get("api_key", ""),
        model_id=model.get("model_id", ""),
        messages=messages,
    ):
        if ev["type"] == "delta":
            text += ev["content"]
            if emit:
                emit({"type": "delta", "content": ev["content"]})
        elif ev["type"] == "done":
            text = (ev["msg"].get("content") or text or "").strip()

    if not text:
        raise RuntimeError("模型未返回任何内容")
    return {
        "text": text,
        "model": model.get("display_name") or model.get("name") or "",
    }
