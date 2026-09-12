"""SQLite 数据存储层"""
import sqlite3
import time
import hashlib
from pathlib import Path
from typing import List, Dict, Optional

from app.paths import DATA_DIR

# 默认管理员账号（密码写死为 agent_admin）
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "agent_admin"

_PWD_SALT = "ly_ai_customer"


def _hash_password(password: str) -> str:
    """密码加盐哈希"""
    return hashlib.sha256((_PWD_SALT + password).encode("utf-8")).hexdigest()


class ModelStorage:
    """模型 / 设置 / 会话 数据存储"""

    def __init__(self, db_dir: str = None):
        if db_dir is None:
            # 默认放在运行时工作区 workspace/data 下
            db_dir = str(DATA_DIR)
        self._db_dir = Path(db_dir)
        self._db_file = self._db_dir / "data.db"
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self._db_file)

    def _init_db(self):
        self._db_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    api_format TEXT NOT NULL,
                    base_url TEXT,
                    model_id TEXT NOT NULL,
                    api_key TEXT,
                    model_type TEXT DEFAULT '对话',
                    multimodal INTEGER DEFAULT 0,
                    model_family TEXT DEFAULT '默认',
                    display_name TEXT,
                    context_input INTEGER DEFAULT 184000,
                    context_output INTEGER DEFAULT 16000,
                    tool_calls INTEGER DEFAULT 200,
                    provider TEXT DEFAULT '自定义',
                    enabled INTEGER DEFAULT 1,
                    is_builtin INTEGER DEFAULT 0,
                    is_default INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT DEFAULT '新对话',
                    model_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kb_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    folder_path TEXT NOT NULL,
                    es_index TEXT NOT NULL,
                    embed_model_id INTEGER,
                    enabled INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'idle',
                    doc_count INTEGER DEFAULT 0,
                    chunk_count INTEGER DEFAULT 0,
                    last_built_at TEXT,
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # 旧库迁移：补充 model_type / is_default / embed_model_id 列
            cols = {r[1] for r in conn.execute("PRAGMA table_info(models)").fetchall()}
            if "model_type" not in cols:
                conn.execute("ALTER TABLE models ADD COLUMN model_type TEXT DEFAULT '对话'")
            if "is_default" not in cols:
                conn.execute("ALTER TABLE models ADD COLUMN is_default INTEGER DEFAULT 0")
            kb_cols = {r[1] for r in conn.execute("PRAGMA table_info(kb_configs)").fetchall()}
            if "embed_model_id" not in kb_cols:
                conn.execute("ALTER TABLE kb_configs ADD COLUMN embed_model_id INTEGER")
            conn.commit()
        self._seed_default_admin()

    # ---------- 用户 ----------
    def _seed_default_admin(self):
        """首次启动时写入默认管理员 admin / agent_admin"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE username=?", (DEFAULT_ADMIN_USERNAME,)
            ).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (DEFAULT_ADMIN_USERNAME, _hash_password(DEFAULT_ADMIN_PASSWORD)),
                )
                conn.commit()

    def get_user_by_username(self, username: str) -> Optional[Dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, username, password_hash, created_at FROM users WHERE username=?",
                (username,),
            ).fetchone()
            return dict(row) if row else None

    def create_user(self, username: str, password: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, _hash_password(password)),
            )
            conn.commit()
            return cur.lastrowid

    def verify_user(self, username: str, password: str) -> bool:
        """校验用户名密码"""
        user = self.get_user_by_username(username)
        if not user:
            return False
        return user["password_hash"] == _hash_password(password)

    # ---------- 全局设置 ----------
    def get_setting(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            ).fetchone()
            return row[0] if row else default

    def set_setting(self, key: str, value: str):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO settings (key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (key, value),
            )
            conn.commit()

    def get_all_settings(self) -> Dict:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            return {r[0]: r[1] for r in rows}

    # ---------- 模型管理 ----------
    def list_models(self) -> List[Dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM models ORDER BY is_builtin DESC, id ASC"
            ).fetchall()
            return [self._normalize(r) for r in rows]

    def _normalize(self, row) -> Dict:
        d = dict(row)
        if 'enabled' in d:
            d['enabled'] = bool(d.get('enabled'))
        if 'is_builtin' in d:
            d['is_builtin'] = bool(d.get('is_builtin'))
        if 'is_default' in d:
            d['is_default'] = bool(d.get('is_default'))
        return d

    def get_model(self, model_id: int) -> Optional[Dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM models WHERE id = ?", (model_id,)
            ).fetchone()
            return self._normalize(row) if row else None

    def add_model(self, data: Dict) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO models
                   (name, api_format, base_url, model_id, api_key, model_type,
                    model_family, display_name,
                    context_input, context_output, tool_calls,
                    provider, enabled, is_builtin)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    data["name"],
                    data.get("api_format", "OpenAI Chat Completions 格式"),
                    data.get("base_url", ""),
                    data["model_id"],
                    data.get("api_key", ""),
                    data.get("model_type", "对话"),
                    data.get("model_family", "默认"),
                    data.get("display_name", ""),
                    int(data.get("context_input", 184000)),
                    int(data.get("context_output", 16000)),
                    int(data.get("tool_calls", 200)),
                    data.get("provider", "自定义"),
                    1 if data.get("enabled", True) else 0,
                    1 if data.get("is_builtin") else 0,
                )
            )
            conn.commit()
            return cur.lastrowid

    def update_model(self, model_id: int, data: Dict):
        with self._connect() as conn:
            conn.execute(
                """UPDATE models SET
                   name=?, api_format=?, base_url=?, model_id=?, api_key=?, model_type=?,
                   model_family=?, display_name=?,
                   context_input=?, context_output=?, tool_calls=?,
                   provider=?, enabled=?, updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (
                    data["name"],
                    data.get("api_format", "OpenAI Chat Completions 格式"),
                    data.get("base_url", ""),
                    data["model_id"],
                    data.get("api_key", ""),
                    data.get("model_type", "对话"),
                    data.get("model_family", "默认"),
                    data.get("display_name", ""),
                    int(data.get("context_input", 184000)),
                    int(data.get("context_output", 16000)),
                    int(data.get("tool_calls", 200)),
                    data.get("provider", "自定义"),
                    1 if data.get("enabled", True) else 0,
                    model_id,
                )
            )
            conn.commit()

    def delete_model(self, model_id: int):
        with self._connect() as conn:
            conn.execute("DELETE FROM models WHERE id=?", (model_id,))
            conn.commit()

    def toggle_enabled(self, model_id: int, enabled: bool):
        with self._connect() as conn:
            conn.execute(
                "UPDATE models SET enabled=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (1 if enabled else 0, model_id),
            )
            conn.commit()

    def set_default_model(self, model_id: int):
        """设为该模型类型的默认（同类型互斥，只有一个默认）"""
        m = self.get_model(model_id)
        if not m:
            raise ValueError(f"模型不存在: id={model_id}")
        mtype = m.get("model_type") or "对话"
        with self._connect() as conn:
            conn.execute("UPDATE models SET is_default=0 WHERE model_type=?", (mtype,))
            conn.execute(
                "UPDATE models SET is_default=1, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (model_id,),
            )
            conn.commit()

    def get_default_model(self, model_type: str = "对话") -> Optional[Dict]:
        """取某类型的默认模型（需启用）；未设默认时回退该类型第一个启用的"""
        mtype = model_type or "对话"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT * FROM models
                   WHERE model_type=? AND is_default=1 AND enabled=1
                   ORDER BY id ASC LIMIT 1""",
                (mtype,),
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT * FROM models WHERE model_type=? AND enabled=1 ORDER BY id ASC LIMIT 1",
                    (mtype,),
                ).fetchone()
            return self._normalize(row) if row else None

    # ---------- 知识库配置 ----------
    def _normalize_kb(self, row) -> Dict:
        d = dict(row)
        d["enabled"] = bool(d.get("enabled"))
        return d

    def list_kbs(self) -> List[Dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM kb_configs ORDER BY id ASC").fetchall()
            return [self._normalize_kb(r) for r in rows]

    def get_kb(self, kb_id: int) -> Optional[Dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM kb_configs WHERE id=?", (kb_id,)).fetchone()
            return self._normalize_kb(row) if row else None

    def add_kb(self, data: Dict) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO kb_configs
                   (name, folder_path, es_index, embed_model_id, enabled, status)
                   VALUES (?,?,?,?,?, 'idle')""",
                (
                    data["name"],
                    data["folder_path"],
                    data["es_index"],
                    data.get("embed_model_id"),
                    1 if data.get("enabled", True) else 0,
                ),
            )
            conn.commit()
            return cur.lastrowid

    def update_kb(self, kb_id: int, data: Dict):
        with self._connect() as conn:
            conn.execute(
                """UPDATE kb_configs SET
                   name=?, folder_path=?, es_index=?, embed_model_id=?, enabled=?,
                   updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (
                    data["name"],
                    data["folder_path"],
                    data["es_index"],
                    data.get("embed_model_id"),
                    1 if data.get("enabled", True) else 0,
                    kb_id,
                ),
            )
            conn.commit()

    def delete_kb(self, kb_id: int):
        with self._connect() as conn:
            conn.execute("DELETE FROM kb_configs WHERE id=?", (kb_id,))
            conn.commit()

    def toggle_kb(self, kb_id: int, enabled: bool):
        with self._connect() as conn:
            conn.execute(
                "UPDATE kb_configs SET enabled=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (1 if enabled else 0, kb_id),
            )
            conn.commit()

    def update_kb_build_state(self, kb_id: int, status: str, doc_count: int = None,
                              chunk_count: int = None, error: str = None):
        """更新构建状态（idle/building/ready/error）"""
        with self._connect() as conn:
            sets = ["status=?", "updated_at=CURRENT_TIMESTAMP"]
            args: List = [status]
            if doc_count is not None:
                sets.append("doc_count=?")
                args.append(doc_count)
            if chunk_count is not None:
                sets.append("chunk_count=?")
                args.append(chunk_count)
            if error is not None:
                sets.append("error=?")
                args.append(error)
            if status == "ready":
                sets.append("last_built_at=?")
                args.append(time.strftime("%Y-%m-%d %H:%M:%S"))
            args.append(kb_id)
            conn.execute(f"UPDATE kb_configs SET {', '.join(sets)} WHERE id=?", args)
            conn.commit()

    # ---------- 聊天会话 ----------
    def create_chat_session(self, model_id=None, title="新对话") -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO chat_sessions (title, model_id) VALUES (?, ?)",
                (title, model_id),
            )
            conn.commit()
            return cur.lastrowid

    def list_chat_sessions(self) -> List[Dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT s.id, s.title, s.model_id,
                          s.created_at, s.updated_at,
                          (SELECT content FROM chat_messages m
                           WHERE m.session_id = s.id AND m.role = 'user'
                           ORDER BY m.id ASC LIMIT 1) AS first_query
                   FROM chat_sessions s
                   ORDER BY s.updated_at DESC, s.id DESC"""
            ).fetchall()
            return [dict(r) for r in rows]

    def get_chat_session(self, session_id: int) -> Optional[Dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM chat_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            return dict(row) if row else None

    def update_chat_session(self, session_id: int, title: str = None, model_id=None):
        with self._connect() as conn:
            if title is not None:
                conn.execute(
                    "UPDATE chat_sessions SET title=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (title, session_id),
                )
            if model_id is not None:
                conn.execute(
                    "UPDATE chat_sessions SET model_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (model_id, session_id),
                )
            conn.execute(
                "UPDATE chat_sessions SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (session_id,),
            )
            conn.commit()

    def delete_chat_session(self, session_id: int):
        with self._connect() as conn:
            conn.execute("DELETE FROM chat_messages WHERE session_id=?", (session_id,))
            conn.execute("DELETE FROM chat_sessions WHERE id=?", (session_id,))
            conn.commit()

    # ---------- 聊天消息 ----------
    def add_chat_message(self, session_id: int, role: str, content: str = "") -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO chat_messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content),
            )
            conn.execute(
                "UPDATE chat_sessions SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (session_id,),
            )
            conn.commit()
            return cur.lastrowid

    def list_chat_messages(self, session_id: int) -> List[Dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT id, session_id, role, content, created_at
                   FROM chat_messages WHERE session_id=? ORDER BY id ASC""",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def count_chat_rounds(self, session_id: int) -> int:
        """统计会话轮数（一条用户消息记为一轮）"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM chat_messages WHERE session_id=? AND role='user'",
                (session_id,),
            ).fetchone()
            return int(row[0]) if row else 0
