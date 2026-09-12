"""知识库：ES 连接 / 文件解析 / 分块 / 向量化 / 构建索引 / 混合检索（关键词 + 向量）"""
import os
import json
import time
import threading
import hashlib
import requests

import jieba
import numpy as np
import faiss
from rank_bm25 import BM25Okapi

from app.paths import KNOWLEDGE_BASE_DIR
from app.storage import ModelStorage
from app.logger import logger

storage = ModelStorage()

# 支持解析的文件后缀
SUPPORTED_EXTS = {".txt", ".md", ".pdf", ".docx", ".xlsx", ".csv"}

# 分块参数
CHUNK_SIZE = 500      # 每块目标字符数
CHUNK_OVERLAP = 50    # 相邻块重叠字符数
EMBED_BATCH = 10      # 每次向量化请求的块数（火山方舟 Embedding 单次 input 上限 10）
EMBED_REQUEST_INTERVAL = 1.5  # 向量化批次间隔（秒），避免触发 API 速率限制
MAX_BULK_MB = 8       # ES bulk 上限（MB）

# ES 全局连接的 settings 表键名
ES_HOST_KEY = "es_host"
ES_USER_KEY = "es_username"
ES_PWD_KEY = "es_password"

# 知识库存储模式：local（本地文件）/ es（Elasticsearch）
KB_MODE_KEY = "kb_mode"
KB_LOCAL_PATH_KEY = "kb_local_path"
DEFAULT_LOCAL_PATH = str(KNOWLEDGE_BASE_DIR)


def get_storage_mode() -> str:
    return storage.get_setting(KB_MODE_KEY, "local") or "local"


def get_local_path() -> str:
    return storage.get_setting(KB_LOCAL_PATH_KEY, "") or DEFAULT_LOCAL_PATH


def set_storage_config(mode: str, local_path: str):
    storage.set_setting(KB_MODE_KEY, "es" if mode == "es" else "local")
    storage.set_setting(KB_LOCAL_PATH_KEY, (local_path or "").strip())


# ---------- ES 连接配置 ----------
def get_es_config() -> dict:
    return {
        "host": storage.get_setting(ES_HOST_KEY, ""),
        "username": storage.get_setting(ES_USER_KEY, ""),
        "password": storage.get_setting(ES_PWD_KEY, ""),
    }


def set_es_config(host: str, username: str, password: str):
    storage.set_setting(ES_HOST_KEY, (host or "").strip())
    storage.set_setting(ES_USER_KEY, (username or "").strip())
    storage.set_setting(ES_PWD_KEY, password or "")


def es_request(method: str, path: str, json_body=None, params=None,
               host: str = None, username: str = None, password: str = None,
               timeout: int = 30):
    """调用 ES REST API，返回 (ok, data)"""
    cfg = get_es_config()
    base = (host or cfg["host"] or "").rstrip("/")
    if not base:
        return False, {"detail": "未配置 ES 地址"}
    if not base.startswith("http"):
        base = "http://" + base
    url = base + path
    auth = None
    user = username if username is not None else cfg["username"]
    pwd = password if password is not None else cfg["password"]
    if user or pwd:
        auth = (user, pwd)
    try:
        resp = requests.request(method, url, json=json_body, params=params,
                                auth=auth, timeout=timeout)
        data = None
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text[:500]}
        if resp.status_code >= 400:
            return False, data
        return True, data
    except requests.RequestException as e:
        return False, {"detail": f"ES 连接失败: {e}"}


def test_es_connection(host: str, username: str, password: str) -> dict:
    """测试 ES 连接，返回集群信息或抛错"""
    ok, data = es_request("GET", "/", host=host, username=username, password=password)
    if not ok:
        detail = data.get("detail") or json.dumps(data, ensure_ascii=False)[:300]
        raise RuntimeError(detail)
    version = (data.get("version") or {})
    return {
        "cluster_name": version.get("cluster_name", ""),
        "es_version": version.get("number", ""),
    }


# ---------- 文件解析 ----------
def _sanitize(text: str) -> str:
    """去除无法 UTF-8 编码的孤立代理字符（源文件/文件名编码异常时可能出现）"""
    return (text or "").encode("utf-8", "ignore").decode("utf-8")


def _tokenize(text: str) -> list:
    """检索用分词：jieba 搜索引擎模式（构建预分词与查询共用，保证词项一致）"""
    return [t for t in jieba.lcut_for_search((text or "").lower()) if t.strip()]


def _pdf_extract(file_path: str) -> str:
    """pdfplumber 解析：表格抽成 '单元格 | 单元格' 行，表格区域外的文字正常抽取（避免内容重复）"""
    import pdfplumber
    parts = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            try:
                tables = page.find_tables()
            except Exception:
                tables = []
            bboxes = [t.bbox for t in tables]
            for t in tables:
                for row in t.extract():
                    cells = [str(c).strip() if c is not None else "" for c in row]
                    if any(cells):
                        parts.append(" | ".join(cells))
            if bboxes:
                # 只保留中心点落在表格区域外的字符，剩下的才是正文
                def keep(obj, _bboxes=tuple(bboxes)):
                    cx = (obj["x0"] + obj["x1"]) / 2
                    cy = (obj["top"] + obj["bottom"]) / 2
                    return not any(bx0 <= cx <= bx1 and btop <= cy <= bbottom
                                   for bx0, btop, bx1, bbottom in _bboxes)
                try:
                    parts.append(page.filter(keep).extract_text() or "")
                except Exception:
                    pass
            else:
                parts.append(page.extract_text() or "")
    return "\n".join(p for p in parts if p.strip())


def _xlsx_extract(file_path: str) -> str:
    """openpyxl 解析：每个工作表标注名称，行内单元格用 ' | ' 连接"""
    from openpyxl import load_workbook
    parts = []
    wb = load_workbook(file_path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            parts.append(f"【工作表: {ws.title}】")
            for row in ws.iter_rows(values_only=True):
                cells = ["" if v is None else str(v).strip() for v in row]
                while cells and cells[-1] == "":
                    cells.pop()
                if cells:
                    parts.append(" | ".join(cells))
    finally:
        wb.close()
    return "\n".join(parts)


def _csv_extract(file_path: str) -> str:
    """csv 解析：自动尝试 utf-8-sig / gbk 编码，行内单元格用 ' | ' 连接"""
    import csv
    with open(file_path, "rb") as f:
        raw = f.read()
    text = None
    for enc in ("utf-8-sig", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", "ignore")
    parts = []
    for row in csv.reader(text.splitlines()):
        cells = [c.strip() for c in row]
        while cells and cells[-1] == "":
            cells.pop()
        if cells:
            parts.append(" | ".join(cells))
    return "\n".join(parts)


def _extract_text(file_path: str) -> str:
    """按后缀提取文本"""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".txt", ".md"):
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    if ext == ".pdf":
        try:
            return _pdf_extract(file_path)
        except Exception as e:
            logger.warning("pdfplumber 解析失败，回退 pypdf 纯文本 %s: %s", file_path, e)
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                pages.append("")
        return "\n".join(pages)
    if ext == ".docx":
        import docx
        d = docx.Document(file_path)
        parts = [p.text for p in d.paragraphs]
        for table in d.tables:
            for row in table.rows:
                cells = [c.text for c in row.cells]
                parts.append(" | ".join(cells))
        return "\n".join(parts)
    if ext == ".xlsx":
        return _xlsx_extract(file_path)
    if ext == ".csv":
        return _csv_extract(file_path)
    return ""


def list_folder_files(folder_path: str):
    """递归列出文件夹下支持的文件"""
    files = []
    for root, _dirs, names in os.walk(folder_path):
        for name in names:
            if os.path.splitext(name)[1].lower() in SUPPORTED_EXTS:
                files.append(os.path.join(root, name))
    return sorted(files)


# ---------- 分块 ----------
def chunk_text(text: str):
    """按段落聚合 + 长度切分为重叠块"""
    text = (text or "").strip()
    if not text:
        return []
    paras = [p.strip() for p in text.replace("\r\n", "\n").split("\n") if p.strip()]
    chunks = []
    buf = ""
    for p in paras:
        # 单段超长：按固定长度硬切
        while len(p) > CHUNK_SIZE:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(p[:CHUNK_SIZE])
            p = p[CHUNK_SIZE - CHUNK_OVERLAP:]
        if not buf:
            buf = p
        elif len(buf) + len(p) + 1 <= CHUNK_SIZE:
            buf += "\n" + p
        else:
            chunks.append(buf)
            buf = p[-CHUNK_OVERLAP:] + "\n" + p if CHUNK_OVERLAP else p
    if buf.strip():
        chunks.append(buf)
    return [c.strip() for c in chunks if c.strip()]


# ---------- Embedding ----------
def embed_texts(texts, base_url, api_key, model, retries: int = 9):
    """调用 OpenAI 兼容 /embeddings 接口，返回向量列表（429/5xx 自动退避重试）"""
    url = (base_url or "").rstrip("/") + "/embeddings"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    for attempt in range(retries):
        resp = requests.post(
            url,
            headers=headers,
            json={"model": model, "input": texts},
            timeout=120,
        )
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
            # 429 优先尊重服务端 Retry-After，否则指数退避至 60s——
            # 账户级限流（TPM/RPM 窗口）通常需等待窗口滚动恢复
            wait = 0
            if resp.status_code == 429:
                try:
                    wait = int(resp.headers.get("Retry-After", ""))
                except (ValueError, TypeError):
                    wait = 0
            if not (0 < wait <= 120):
                wait = min(2 ** (attempt + 1), 60)
            logger.warning("Embedding 暂时失败(HTTP %s)，%ss 后重试(%s/%s)",
                           resp.status_code, wait, attempt + 1, retries - 1)
            time.sleep(wait)
            continue
        break
    if resp.status_code >= 400:
        raise RuntimeError(f"Embedding 调用失败(HTTP {resp.status_code}): {resp.text[:300]}")
    data = resp.json()
    items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
    vectors = [it["embedding"] for it in items]
    if len(vectors) != len(texts):
        raise RuntimeError(f"Embedding 返回数量不符: 期望 {len(texts)} 实得 {len(vectors)}")
    return vectors


def resolve_embed_config(kb: dict):
    """从模型配置中解析知识库的向量化配置（引用 embed_model_id）

    返回 {base_url, api_key, model}；未选择模型或模型已删除返回 None（仅关键词检索）
    """
    mid = kb.get("embed_model_id")
    if not mid:
        return None
    m = storage.get_model(int(mid))
    if not m or not m.get("base_url") or not m.get("model_id"):
        return None
    return {
        "base_url": m["base_url"],
        "api_key": m.get("api_key") or "",
        "model": m["model_id"],
    }


# ---------- 本地存储后端 ----------
def _safe_slug(name: str) -> str:
    """索引名/目录名的安全字符集"""
    return "".join(c for c in (name or "") if c.isalnum() or c == "_") or None


def local_kb_file(kb: dict) -> str:
    """本地模式下知识库分块文件的最终保存路径"""
    slug = _safe_slug(kb.get("es_index")) or f"kb_{kb['id']}"
    return os.path.join(get_local_path(), slug, "chunks.json")


def local_vector_file(kb: dict) -> str:
    """本地模式下向量索引（FAISS）文件的保存路径"""
    kb_file = local_kb_file(kb)
    return os.path.join(os.path.dirname(kb_file), "vectors.faiss")


def _write_local_kb(kb_file: str, kb: dict, docs, tokens_list, vectors, model_name: str):
    """写入本地知识库：chunks.json（文本+预分词）+ vectors.faiss（向量索引）"""
    items = []
    for idx, (doc_name, ci, content) in enumerate(docs):
        it = {"doc_name": doc_name, "chunk_index": ci, "content": content}
        if tokens_list:
            it["tokens"] = tokens_list[idx]
        items.append(it)
    payload = {
        "kb_id": kb["id"],
        "kb_name": kb["name"],
        "model": model_name or "",
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "chunk_count": len(items),
        "docs": items,
    }
    os.makedirs(os.path.dirname(kb_file), exist_ok=True)
    tmp = kb_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, kb_file)

    # 向量单独存 FAISS 索引：IndexFlatIP + L2 归一化 = cosine 相似度
    vec_file = local_vector_file(kb)
    if vectors:
        mat = np.array(vectors, dtype="float32")
        faiss.normalize_L2(mat)
        index = faiss.IndexFlatIP(mat.shape[1])
        index.add(mat)
        faiss.write_index(index, vec_file)
    elif os.path.isfile(vec_file):
        os.remove(vec_file)  # 无向量构建时清掉旧索引，避免与分块错位


def delete_local_kb(kb: dict):
    """删除本地知识库文件（整个知识库目录）"""
    slug = _safe_slug(kb.get("es_index")) or f"kb_{kb['id']}"
    kb_dir = os.path.join(get_local_path(), slug)
    if os.path.isdir(kb_dir):
        import shutil
        shutil.rmtree(kb_dir, ignore_errors=True)


# 本地检索索引缓存：{kb_file: (mtime, docs, bm25, faiss_index)}，重建后自动失效
_LOCAL_CACHE = {}


def _load_local_index(kb_file: str):
    """加载本地知识库并构建 BM25 / FAISS 索引（按 chunks.json 的 mtime 缓存）"""
    try:
        mtime = os.path.getmtime(kb_file)
    except OSError:
        return None, None, None
    cached = _LOCAL_CACHE.get(kb_file)
    if cached and cached[0] == mtime:
        return cached[1], cached[2], cached[3]
    try:
        with open(kb_file, "r", encoding="utf-8") as f:
            docs = json.load(f).get("docs") or []
    except Exception as e:
        logger.warning("读取本地知识库失败 %s: %s", kb_file, e)
        return None, None, None

    corpus = []
    for d in docs:
        tokens = d.get("tokens")
        if tokens is None:  # 旧版本数据无预分词：查询时现场分词兜底
            tokens = _tokenize(d.get("content", ""))
        corpus.append(tokens)
    try:
        bm25 = BM25Okapi(corpus) if corpus and any(corpus) else None
    except Exception as e:
        logger.warning("构建本地 BM25 索引失败 %s: %s", kb_file, e)
        bm25 = None

    vec_file = os.path.join(os.path.dirname(kb_file), "vectors.faiss")
    index = None
    if os.path.isfile(vec_file):
        try:
            index = faiss.read_index(vec_file)
        except Exception as e:
            logger.warning("读取向量索引失败 %s: %s", vec_file, e)
    if index is not None and index.ntotal != len(docs):
        logger.warning("向量索引数(%s)与分块数(%s)不一致，忽略向量检索: %s",
                       index.ntotal, len(docs), kb_file)
        index = None

    _LOCAL_CACHE[kb_file] = (mtime, docs, bm25, index)
    return docs, bm25, index


def search_local_kb(kb: dict, query: str, qvec, top_k: int):
    """本地知识库检索：BM25 关键词 + FAISS 向量，RRF 融合"""
    kb_file = local_kb_file(kb)
    if not os.path.isfile(kb_file):
        return []
    docs, bm25, index = _load_local_index(kb_file)
    if not docs:
        return []

    rankings = []
    if bm25:
        q_tokens = _tokenize(query)
        if q_tokens:
            scores = bm25.get_scores(q_tokens)
            kw_rank = [i for i, _ in sorted(enumerate(scores), key=lambda x: -x[1])[:10]
                       if scores[i] > 0]
            if kw_rank:
                rankings.append(kw_rank)

    if qvec is not None and index is not None and index.ntotal:
        q = np.array([qvec], dtype="float32")
        faiss.normalize_L2(q)
        faiss_scores, faiss_ids = index.search(q, min(10, index.ntotal))
        vec_rank = [int(i) for i in faiss_ids[0] if i != -1]
        if vec_rank:
            rankings.append(vec_rank)

    selected = []
    for i in _rrf_merge(rankings, top_n=top_k):
        d = docs[i]
        selected.append({
            "kb": kb["name"],
            "doc": d.get("doc_name", ""),
            "content": d.get("content", ""),
        })
    return selected


# ---------- 构建索引 ----------
def _create_index(index: str, dims: int) -> tuple:
    """删除并重建 ES 索引，返回 (ok, err)"""
    es_request("DELETE", f"/{index}")
    mapping = {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
        "mappings": {
            "properties": {
                "kb_id": {"type": "keyword"},
                "doc_name": {"type": "keyword"},
                "content": {"type": "text"},
                "chunk_index": {"type": "integer"},
                "vector": {
                    "type": "dense_vector",
                    "dims": dims,
                    "index": True,
                    "similarity": "cosine",
                },
            }
        },
    }
    ok, data = es_request("PUT", f"/{index}", json_body=mapping)
    if not ok:
        return False, json.dumps(data, ensure_ascii=False)[:300]
    return True, None


def _bulk_index(index: str, docs) -> tuple:
    """批量索引文档：按请求体大小自动分批提交，docs 为 [{kb_id, doc_name, content, chunk_index, vector}]"""
    cfg = get_es_config()
    base = cfg["host"].rstrip("/")
    if not base.startswith("http"):
        base = "http://" + base
    auth = None
    if cfg["username"] or cfg["password"]:
        auth = (cfg["username"], cfg["password"])

    limit = MAX_BULK_MB * 1024 * 1024

    def _post(batch) -> tuple:
        lines = []
        for d in batch:
            lines.append(json.dumps({"index": {"_index": index}}, ensure_ascii=False))
            lines.append(json.dumps(d, ensure_ascii=False))
        body = ("\n".join(lines) + "\n").encode("utf-8")
        try:
            resp = requests.post(
                f"{base}/_bulk",
                params={"refresh": "wait_for"},
                data=body,
                headers={"Content-Type": "application/x-ndjson; charset=utf-8"},
                auth=auth,
                timeout=300,
            )
            if resp.status_code >= 400:
                return False, resp.text[:300]
            result = resp.json()
            if result.get("errors"):
                return False, json.dumps(result.get("items", [])[:2], ensure_ascii=False)[:300]
            return True, None
        except requests.RequestException as e:
            return False, f"ES bulk 失败: {e}"

    batch, size = [], 0
    for d in docs:
        # 估算单条体积（meta 行 + 内容 + 换行），攒到上限前提交一批
        n = len(json.dumps(d, ensure_ascii=False).encode("utf-8")) + 64
        if batch and size + n > limit:
            ok, err = _post(batch)
            if not ok:
                return False, err
            batch, size = [], 0
        batch.append(d)
        size += n
    if batch:
        return _post(batch)
    return True, None


def build_knowledge_base(kb_id: int):
    """构建知识库（后台线程执行）：解析文件夹 -> 分块 -> 向量化 -> 写入 ES"""
    kb = storage.get_kb(kb_id)
    if not kb:
        return

    def worker():
        try:
            storage.update_kb_build_state(kb_id, "building", error=None)
            folder = kb["folder_path"]
            if not os.path.isdir(folder):
                raise RuntimeError(f"文件夹不存在: {folder}")

            files = list_folder_files(folder)
            if not files:
                raise RuntimeError(
                    f"文件夹中没有可解析的文件（支持 {', '.join(sorted(SUPPORTED_EXTS))}）")

            # 提取文本 + 分块
            docs = []  # (doc_name, chunk_index, content)
            for fp in files:
                try:
                    text = _sanitize(_extract_text(fp))
                except Exception as e:
                    logger.warning("知识库解析文件失败 %s: %s", fp, e)
                    continue
                for i, ck in enumerate(chunk_text(text)):
                    docs.append((_sanitize(os.path.basename(fp)), i, ck))
            if not docs:
                raise RuntimeError("所有文件均未解析出文本内容")

            # 预分词（本地 BM25 检索用；ES 模式由服务端自行分词建倒排索引）
            tokens_list = [_tokenize(c[2]) for c in docs]

            # 向量化（可选：未选择向量化模型则只用关键词检索）
            vectors = None
            dims = None
            embed_cfg = resolve_embed_config(kb)
            if embed_cfg:
                storage.update_kb_build_state(kb_id, "building")
                texts = [c[2] for c in docs]
                vectors = []
                for i in range(0, len(texts), EMBED_BATCH):
                    batch = texts[i:i + EMBED_BATCH]
                    if i:  # 批次间限速，避免请求过密触发 429
                        time.sleep(EMBED_REQUEST_INTERVAL)
                    vectors.extend(embed_texts(
                        batch, embed_cfg["base_url"], embed_cfg["api_key"], embed_cfg["model"]))
                dims = len(vectors[0])

            # 按存储模式写入
            mode = get_storage_mode()
            model_name = embed_cfg["model"] if embed_cfg else ""
            if mode == "local":
                kb_file = local_kb_file(kb)
                _write_local_kb(kb_file, kb, docs, tokens_list, vectors, model_name)
                target = kb_file
            else:
                index = kb["es_index"]
                if vectors:
                    ok, err = _create_index(index, dims)
                    if not ok:
                        raise RuntimeError(f"创建 ES 索引失败: {err}")

                bulk_docs = []
                for idx, (doc_name, ci, content) in enumerate(docs):
                    item = {
                        "kb_id": str(kb_id),
                        "doc_name": doc_name,
                        "content": content,
                        "chunk_index": ci,
                    }
                    if vectors:
                        item["vector"] = vectors[idx]
                    bulk_docs.append(item)

                ok, err = _bulk_index(index, bulk_docs)
                if not ok:
                    raise RuntimeError(f"写入 ES 失败: {err}")
                target = index

            n_files = len({d[0] for d in docs})
            storage.update_kb_build_state(
                kb_id, "ready", doc_count=n_files, chunk_count=len(docs))
            logger.info("知识库构建完成 id=%s 模式=%s 目标=%s 文件=%s 分块=%s 向量=%s",
                        kb_id, mode, target, n_files, len(docs), bool(vectors))
        except Exception as e:
            logger.error("知识库构建失败 id=%s: %s", kb_id, e, exc_info=True)
            storage.update_kb_build_state(kb_id, "error", error=str(e))

    threading.Thread(target=worker, daemon=True).start()


def delete_es_index(index: str):
    """删除知识库对应的 ES 索引"""
    es_request("DELETE", f"/{index}")


def delete_kb_data(kb: dict):
    """删除知识库的存储数据（按当前存储模式）"""
    if get_storage_mode() == "local":
        delete_local_kb(kb)
    else:
        delete_es_index(kb["es_index"])


# ---------- 检索（对话 RAG 用） ----------
def _rrf_merge(rankings, k=60, top_n=8):
    """RRF 融合多路检索结果：rankings = [ [chunk_key, ...], ... ]"""
    scores = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking):
            scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
    return [key for key, _ in sorted(scores.items(), key=lambda x: -x[1])[:top_n]]


def search_knowledge(query: str, top_k: int = 5):
    """在所有启用的知识库中混合检索（关键词 + 向量，RRF 融合）

    根据全局存储模式从本地文件或 ES 检索。
    Returns: [{"kb": 名称, "doc": 文件名, "content": 文本}]
    """
    if not query or not query.strip():
        return []
    kbs = [k for k in storage.list_kbs() if k["enabled"] and k["status"] == "ready"]
    if not kbs:
        return []

    mode = get_storage_mode()
    if mode == "local":
        selected = []
        for kb in kbs:
            qvec = None
            embed_cfg = resolve_embed_config(kb)
            if embed_cfg:
                try:
                    qvec = embed_texts([query.strip()], embed_cfg["base_url"],
                                       embed_cfg["api_key"], embed_cfg["model"])[0]
                except Exception as e:
                    logger.warning("知识库向量检索失败（降级为关键词检索）: %s", e)
            selected.extend(search_local_kb(kb, query, qvec, top_k))
        return selected

    selected = []
    for kb in kbs:
        index = kb["es_index"]
        items = {}  # key -> {kb, doc, content}

        # 1) BM25 关键词检索
        ok, data = es_request("POST", f"/{index}/_search", json_body={
            "size": 10,
            "query": {
                "bool": {
                    "must": [{"match": {"content": {"query": query}}}],
                    "filter": [{"term": {"kb_id": str(kb["id"])}}],
                }
            },
        })
        bm25_ranking = []
        if ok:
            for hit in (data.get("hits", {}).get("hits", []) or []):
                key = hit["_id"]
                src = hit.get("_source", {})
                items[key] = {
                    "kb": kb["name"],
                    "doc": src.get("doc_name", ""),
                    "content": src.get("content", ""),
                }
                bm25_ranking.append(key)

        # 2) kNN 向量检索（选择了向量化模型才执行）
        rankings = [bm25_ranking]
        embed_cfg = resolve_embed_config(kb)
        if embed_cfg:
            try:
                qvec = embed_texts([query.strip()], embed_cfg["base_url"],
                                   embed_cfg["api_key"], embed_cfg["model"])[0]
                ok, data = es_request("POST", f"/{index}/_search", json_body={
                    "size": 10,
                    "knn": {
                        "field": "vector",
                        "query_vector": qvec,
                        "k": 10,
                        "num_candidates": 100,
                        "filter": {"term": {"kb_id": str(kb["id"])}},
                    },
                })
                if ok:
                    knn_ranking = []
                    for hit in (data.get("hits", {}).get("hits", []) or []):
                        key = hit["_id"]
                        if key not in items:
                            src = hit.get("_source", {})
                            items[key] = {
                                "kb": kb["name"],
                                "doc": src.get("doc_name", ""),
                                "content": src.get("content", ""),
                            }
                        knn_ranking.append(key)
                    rankings.append(knn_ranking)
            except Exception as e:
                logger.warning("知识库向量检索失败（降级为关键词检索）: %s", e)

        # RRF 融合排序后取 top_k
        for key in _rrf_merge(rankings, top_n=top_k):
            if key in items:
                selected.append(items[key])
    return selected
