"""FastAPI 后端：模型管理 / 设置 / 客服对话 REST API + 静态文件服务"""
import os
import json
import time
import queue
import string
import threading
import traceback
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional

from app.storage import ModelStorage
from app.logger import logger
from app import knowledge


app = FastAPI(title="Ly AI Customer API", version="1.0.0")
storage = ModelStorage()


# ---------- 全局请求 / 异常日志 ----------
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.time()
    try:
        response = await call_next(request)
        dur = (time.time() - start) * 1000
        if response.status_code >= 400:
            logger.warning(
                "HTTP %s %s -> %s (%dms)", request.method, request.url.path,
                response.status_code, dur,
            )
        else:
            logger.info(
                "HTTP %s %s -> %s (%dms)", request.method, request.url.path,
                response.status_code, dur,
            )
        return response
    except Exception:
        logger.error(
            "请求异常 %s %s\n%s",
            request.method, request.url.path, traceback.format_exc(),
        )
        raise


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("未处理异常 %s %s\n%s", request.method, request.url.path, traceback.format_exc())
    return JSONResponse(status_code=500, content={"detail": f"服务器内部错误: {exc}"})


# ---------- 用户认证 API ----------
class LoginIn(BaseModel):
    username: str
    password: str


class RegisterIn(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def auth_login(data: LoginIn):
    """登录校验"""
    username = (data.username or "").strip()
    if not username or not data.password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    if not storage.verify_user(username, data.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    logger.info("用户登录成功: %s", username)
    return {"ok": True, "username": username}


@app.post("/api/auth/register")
def auth_register(data: RegisterIn):
    """注册新用户"""
    username = (data.username or "").strip()
    if not username or not data.password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="用户名至少 3 个字符")
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 个字符")
    if storage.get_user_by_username(username):
        raise HTTPException(status_code=400, detail="用户名已存在")
    uid = storage.create_user(username, data.password)
    logger.info("用户注册成功: %s (id=%s)", username, uid)
    return {"ok": True, "id": uid, "username": username}


# ---------- 全局设置 API ----------
class SettingIn(BaseModel):
    key: str
    value: str


@app.get("/api/settings")
def get_settings():
    return storage.get_all_settings()


@app.post("/api/settings")
def set_setting(data: SettingIn):
    storage.set_setting(data.key, data.value)
    return {"message": "Saved"}


# ---------- 数据模型 ----------
class ModelIn(BaseModel):
    name: str
    api_format: str = "OpenAI Chat Completions 格式"
    base_url: str = ""
    model_id: str
    api_key: str = ""
    model_type: str = "对话"
    model_family: str = "默认"
    display_name: str = ""
    context_input: int = 184000
    context_output: int = 16000
    tool_calls: int = 200
    provider: str = "自定义"
    enabled: bool = True
    is_builtin: bool = False


class ModelUpdate(BaseModel):
    name: Optional[str] = None
    api_format: Optional[str] = None
    base_url: Optional[str] = None
    model_id: Optional[str] = None
    api_key: Optional[str] = None
    model_type: Optional[str] = None
    model_family: Optional[str] = None
    display_name: Optional[str] = None
    context_input: Optional[int] = None
    context_output: Optional[int] = None
    tool_calls: Optional[int] = None
    provider: Optional[str] = None
    enabled: Optional[bool] = None


# ---------- 模型 API ----------
@app.get("/api/models")
def list_models():
    return storage.list_models()


@app.get("/api/models/{model_id}")
def get_model(model_id: int):
    m = storage.get_model(model_id)
    if not m:
        raise HTTPException(status_code=404, detail="Model not found")
    return m


@app.post("/api/models")
def create_model(data: ModelIn):
    mid = storage.add_model(data.dict())
    return {"id": mid, "message": "Created"}


@app.put("/api/models/{model_id}")
def update_model(model_id: int, data: ModelUpdate):
    existing = storage.get_model(model_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Model not found")
    merged = {**existing, **{k: v for k, v in data.dict().items() if v is not None}}
    storage.update_model(model_id, merged)
    return {"message": "Updated"}


@app.delete("/api/models/{model_id}")
def delete_model(model_id: int):
    storage.delete_model(model_id)
    return {"message": "Deleted"}


@app.post("/api/models/{model_id}/duplicate")
def duplicate_model(model_id: int):
    """复制模型：基于已有模型创建一条新记录，名称加「副本」后缀"""
    existing = storage.get_model(model_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Model not found")
    # 去掉 id，改名字，确保不是内置模型
    new_data = {k: v for k, v in existing.items() if k != "id"}
    new_data["name"] = (existing.get("name") or "模型") + " 副本"
    if existing.get("display_name"):
        new_data["display_name"] = existing["display_name"] + " 副本"
    new_data["is_builtin"] = False
    new_id = storage.add_model(new_data)
    return {"id": new_id, "message": "Duplicated"}


@app.patch("/api/models/{model_id}/toggle")
def toggle_model(model_id: int, enabled: bool):
    storage.toggle_enabled(model_id, enabled)
    return {"message": "Toggled"}


@app.post("/api/models/{model_id}/default")
def set_default_model(model_id: int):
    """设为该类型的默认模型（同类型互斥）"""
    try:
        storage.set_default_model(model_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"message": "Default set"}


# ---------- 知识库 API ----------
class ESConfigIn(BaseModel):
    host: str
    username: str = ""
    password: str = ""


class StorageConfigIn(BaseModel):
    mode: str = "local"
    local_path: str = ""
    host: str = ""
    username: str = ""
    password: str = ""


class KBIn(BaseModel):
    name: str
    folder_path: str
    es_index: str = ""
    embed_model_id: Optional[int] = None
    enabled: bool = True


@app.get("/api/kb/storage-config")
def get_storage_config():
    """获取知识库存储配置（模式 + 本地路径 + ES 连接，密码打码）"""
    cfg = knowledge.get_es_config()
    if cfg["password"]:
        cfg["password"] = "******"
    return {
        "mode": knowledge.get_storage_mode(),
        "local_path": knowledge.get_local_path(),
        **cfg,
    }


@app.post("/api/kb/storage-config")
def save_storage_config(data: StorageConfigIn):
    """保存知识库存储配置；ES 密码为打码值时保留原密码"""
    old = knowledge.get_es_config()
    password = data.password
    if password == "******":
        password = old["password"]
    knowledge.set_storage_config(data.mode, data.local_path)
    knowledge.set_es_config(data.host, data.username, password)
    return {"message": "Saved"}


@app.get("/api/kb/es-config")
def get_es_config():
    """获取 ES 连接配置（密码打码）"""
    cfg = knowledge.get_es_config()
    if cfg["password"]:
        cfg["password"] = "******"
    return cfg


@app.post("/api/kb/es-config")
def save_es_config(data: ESConfigIn):
    """保存 ES 连接配置；密码为打码值时保留原密码"""
    old = knowledge.get_es_config()
    password = data.password
    if password == "******":
        password = old["password"]
    knowledge.set_es_config(data.host, data.username, password)
    return {"message": "Saved"}


@app.post("/api/kb/es-config/test")
def test_es_config(data: ESConfigIn):
    """测试 ES 连接"""
    password = data.password
    if password == "******":
        password = knowledge.get_es_config()["password"]
    try:
        info = knowledge.test_es_connection(data.host, data.username, password)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, **info}


@app.get("/api/kb")
def list_kbs():
    rows = storage.list_kbs()
    # 附上每个知识库的最终存储位置（本地文件路径或 ES 索引名）
    mode = knowledge.get_storage_mode()
    for kb in rows:
        if mode == "local":
            kb["store_location"] = knowledge.local_kb_file(kb)
        else:
            kb["store_location"] = kb["es_index"]
    return rows


def _generate_es_index(name: str) -> str:
    """新建知识库时根据名称生成唯一的索引名/本地目录名：kb_{拼音}，重名自动加序号"""
    try:
        from pypinyin import lazy_pinyin
        # 汉字转拼音，其余字符原样保留
        text = "".join(lazy_pinyin(name or ""))
    except ImportError:
        logger.warning("pypinyin 未安装，索引名中的中文将被忽略（可执行 pip install pypinyin）")
        text = name or ""
    # 仅保留 ASCII 字母/数字/下划线，其余替换为 _；ES 索引名要求小写
    slug = "".join(c if (c.isascii() and (c.isalnum() or c == "_")) else "_" for c in text.lower())
    slug = slug.strip("_") or "kb"
    if not slug[0].isalnum():  # ES 索引名不能以 _ 开头
        slug = "kb" + slug
    slug = slug[:40].rstrip("_")  # 控制长度，留出重名后缀空间
    existing = {k["es_index"] for k in storage.list_kbs()}
    candidate = f"kb_{slug}"
    n = 2
    while candidate in existing:
        candidate = f"kb_{slug}_{n}"
        n += 1
    return candidate


@app.post("/api/kb")
def create_kb(data: KBIn):
    name = (data.name or "").strip()
    folder = (data.folder_path or "").strip()
    if not name or not folder:
        raise HTTPException(status_code=400, detail="名称和文件路径不能为空")
    if (data.es_index or "").strip():
        es_index = data.es_index.strip()
        if not es_index.replace("_", "").isalnum():
            raise HTTPException(status_code=400, detail="索引名只能包含字母、数字、下划线")
    else:
        es_index = _generate_es_index(name)  # 仅新建留空时按名称自动生成，保证唯一
    kid = storage.add_kb({
        "name": name, "folder_path": folder, "es_index": es_index,
        "embed_model_id": data.embed_model_id,
        "enabled": data.enabled,
    })
    return {"id": kid, "message": "Created"}


@app.put("/api/kb/{kb_id}")
def update_kb(kb_id: int, data: KBIn):
    kb = storage.get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    merged = {**kb, **data.dict()}
    storage.update_kb(kb_id, merged)
    return {"message": "Updated"}


@app.delete("/api/kb/{kb_id}")
def delete_kb(kb_id: int):
    kb = storage.get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    knowledge.delete_kb_data(kb)
    storage.delete_kb(kb_id)
    return {"message": "Deleted"}


@app.patch("/api/kb/{kb_id}/toggle")
def toggle_kb(kb_id: int, enabled: bool):
    storage.toggle_kb(kb_id, enabled)
    return {"message": "Toggled"}


@app.post("/api/kb/{kb_id}/build")
def build_kb(kb_id: int):
    """生成知识库：后台解析文件夹 -> 分块 -> 向量化 -> 按存储模式写入本地/ES"""
    kb = storage.get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if kb["status"] == "building":
        raise HTTPException(status_code=400, detail="知识库正在构建中")
    if knowledge.get_storage_mode() == "es":
        cfg = knowledge.get_es_config()
        if not cfg["host"]:
            raise HTTPException(status_code=400, detail="请先在上方配置并保存 ES 连接")
    else:
        if not knowledge.get_local_path():
            raise HTTPException(status_code=400, detail="请先配置本地知识库保存路径")
    knowledge.build_knowledge_base(kb_id)
    return {"message": "Build started"}


# ---------- 服务器目录浏览（文件夹选择控件，只读） ----------
@app.get("/api/fs/dirs")
def list_dirs(path: str = ""):
    """浏览服务器本地目录：path 为空时返回根列表（Windows 为盘符，其他为 /）"""
    if not path:
        if os.name == "nt":
            drives = [f"{l}:\\" for l in string.ascii_uppercase
                      if Path(f"{l}:\\").exists()]
            return {"path": "", "parent": None, "dirs": drives}
        path = "/"
    try:
        p = Path(path).resolve()
        if not p.is_dir():
            raise HTTPException(status_code=400, detail="路径不存在或不是文件夹")
        dirs = []
        try:
            children = sorted(p.iterdir(), key=lambda c: c.name.lower())
            dirs = [str(c) for c in children if c.is_dir()]
        except (PermissionError, OSError):
            pass  # 无权限或读取失败时按空目录返回
        parent = str(p.parent) if p.parent != p else ""
        return {"path": str(p), "parent": parent, "dirs": dirs}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="无法访问该路径")


# ---------- 聊天会话 API ----------
class ChatSessionIn(BaseModel):
    title: str = "新对话"
    model_id: Optional[int] = None


@app.get("/api/chats")
def list_chats():
    """列出全部会话（按最近更新排序）"""
    return {"items": storage.list_chat_sessions()}


@app.post("/api/chats")
def create_chat(data: ChatSessionIn):
    sid = storage.create_chat_session(data.model_id, data.title)
    return {"id": sid, "title": data.title}


@app.get("/api/chats/{session_id}")
def get_chat(session_id: int):
    session = storage.get_chat_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    session["messages"] = storage.list_chat_messages(session_id)
    return session


@app.patch("/api/chats/{session_id}")
def update_chat(session_id: int, data: ChatSessionIn):
    if not storage.get_chat_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    storage.update_chat_session(session_id, title=data.title, model_id=data.model_id)
    return {"ok": True}


@app.delete("/api/chats/{session_id}")
def delete_chat(session_id: int):
    storage.delete_chat_session(session_id)
    return {"ok": True}


# ---------- 智能客服对话 API ----------
class ChatQueryIn(BaseModel):
    model_id: int
    user_query: str
    session_id: Optional[int] = None


def _chat_log_ctx(data: "ChatQueryIn", session_id) -> str:
    """对话失败日志的上下文信息（会话/模型/问题），方便事后排查"""
    return (f"session={session_id} model={data.model_id} "
            f"query={(data.user_query or '')[:200]!r}")


# 会话 -> 待确认工具上下文（内存缓存，确认/取消时取用；30 分钟过期）
_PENDING_TOOLS: dict = {}
_PENDING_TTL = 30 * 60


def _pending_put(session_id: int, model_id: int, result: dict):
    _PENDING_TOOLS[session_id] = {
        "model_id": model_id,
        "pending_tool": result["pending_tool"],
        "resume_messages": result["resume_messages"],
        "ts": time.time(),
    }


def _pending_pop(session_id: int):
    state = _PENDING_TOOLS.pop(session_id, None)
    if state and time.time() - state["ts"] > _PENDING_TTL:
        return None
    return state


@app.post("/api/chat/stream")
def chat_stream(data: ChatQueryIn):
    """智能客服流式接口（SSE）：LLM 文本增量实时推送，避免长时间等待超时

    事件类型：
        session -> {"session_id": ...}
        delta   -> {"content": ...}（LLM 文本增量）
        final   -> {"text": ..., "model": ..., "session_id": ...}
        error   -> {"detail": ...}
    """
    def sse(obj):
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    q = queue.Queue()

    def worker():
        session_id = data.session_id
        try:
            from app.agent import run_chat

            # 无会话则创建，标题取用户输入前20字
            if not session_id:
                title = (data.user_query or "新对话").strip()[:20] or "新对话"
                session_id = storage.create_chat_session(data.model_id, title)
            q.put(sse({"type": "session", "session_id": session_id}))

            # 记录用户消息
            storage.add_chat_message(session_id, "user", data.user_query)

            # 取历史消息作为上下文（压缩：最多8条，去掉刚记录的当前这条）
            history = storage.list_chat_messages(session_id)
            context = [m for m in history[-9:-1]
                       if m["role"] in ("user", "assistant") and m.get("content")]

            result = run_chat(data.model_id, data.user_query,
                              history=context,
                              emit=lambda ev: q.put(sse(ev)))

            if result.get("pending_tool"):
                # 写工具待确认：暂存上下文，等待前端调 /api/chat/confirm 恢复
                _pending_put(session_id, data.model_id, result)
                q.put(sse({
                    "type": "final",
                    "text": None,
                    "model": result.get("model", ""),
                    "session_id": session_id,
                    "tool_trace": result.get("tool_trace") or [],
                    "pending_tool": result["pending_tool"],
                }))
                return

            # 记录助手消息
            storage.add_chat_message(session_id, "assistant", result["text"])
            result["session_id"] = session_id
            # 统计会话轮数，超过上限时提示用户开启新对话
            rounds = storage.count_chat_rounds(session_id)
            result["history_rounds"] = rounds
            result["history_exceeded"] = rounds > 200
            q.put(sse({"type": "final", **result}))
        except ValueError as e:
            logger.warning("客服对话失败(业务校验): %s | %s", e, _chat_log_ctx(data, session_id))
            q.put(sse({"type": "error", "detail": str(e)}))
        except RuntimeError as e:
            logger.error("客服对话失败(模型调用): %s | %s", e, _chat_log_ctx(data, session_id), exc_info=True)
            q.put(sse({"type": "error", "detail": str(e)}))
        except Exception as e:
            logger.error("客服对话异常: %s | %s", e, _chat_log_ctx(data, session_id), exc_info=True)
            q.put(sse({"type": "error", "detail": f"对话失败: {e}"}))
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def gen():
        while True:
            item = q.get()
            if item is None:
                break
            yield item

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- 工具执行确认 API ----------
class ChatConfirmIn(BaseModel):
    session_id: int
    action: str = "confirm"  # confirm / cancel


@app.post("/api/chat/confirm")
def chat_confirm(data: ChatConfirmIn):
    """待确认工具的确认/取消接口（SSE）

    confirm -> 执行暂存的写工具，恢复工具循环直至最终回复（或下一个待确认工具）
    cancel  -> 放弃执行，记录一条"已取消"助手消息
    """
    def sse(obj):
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    q = queue.Queue()

    def worker():
        session_id = data.session_id
        try:
            state = _pending_pop(session_id)
            if not state:
                raise ValueError("没有待确认的工具执行请求，可能已过期或已处理")

            if (data.action or "confirm").lower() != "confirm":
                pt = state["pending_tool"]
                text = f"已取消执行工具「{pt.get('summary') or pt.get('name')}」。"
                storage.add_chat_message(session_id, "assistant", text)
                q.put(sse({"type": "delta", "content": text}))
                q.put(sse({"type": "final", "text": text, "model": "",
                           "session_id": session_id, "tool_trace": []}))
                return

            from app.agent import execute_pending_tool, load_model
            model = load_model(state["model_id"])
            result = execute_pending_tool(
                model, state["pending_tool"], state["resume_messages"],
                emit=lambda ev: q.put(sse(ev)))

            if result.get("pending_tool"):
                # 链式写工具：继续等待下一次确认
                _pending_put(session_id, state["model_id"], result)
                q.put(sse({
                    "type": "final",
                    "text": None,
                    "model": result.get("model", ""),
                    "session_id": session_id,
                    "tool_trace": result.get("tool_trace") or [],
                    "pending_tool": result["pending_tool"],
                }))
                return

            storage.add_chat_message(session_id, "assistant", result["text"])
            q.put(sse({
                "type": "final",
                "text": result["text"],
                "model": result.get("model", ""),
                "session_id": session_id,
                "tool_trace": result.get("tool_trace") or [],
            }))
        except ValueError as e:
            logger.warning("工具确认失败(业务校验): %s | session=%s", e, session_id)
            q.put(sse({"type": "error", "detail": str(e)}))
        except RuntimeError as e:
            logger.error("工具确认失败(模型调用): %s | session=%s", e, session_id, exc_info=True)
            q.put(sse({"type": "error", "detail": str(e)}))
        except Exception as e:
            logger.error("工具确认异常: %s | session=%s", e, session_id, exc_info=True)
            q.put(sse({"type": "error", "detail": f"确认失败: {e}"}))
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def gen():
        while True:
            item = q.get()
            if item is None:
                break
            yield item

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- 插件系统：注册 /api/plugins 路由 + 启动时加载已启用插件的工具 ----------
from app.plugins_api import router as plugins_router  # noqa: E402
app.include_router(plugins_router)
from app.plugin_manager import load_all_plugins  # noqa: E402
load_all_plugins()


# ---------- 静态文件服务（生产环境：Vue 构建产物）----------
WEB_DIST = Path(os.path.abspath(os.path.dirname(__file__))).parent / "web" / "dist"
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(WEB_DIST / "index.html")

    @app.get("/settings/{path:path}")
    def settings_fallback(path: str):
        return FileResponse(WEB_DIST / "index.html")
