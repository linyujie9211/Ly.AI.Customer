"""插件管理：扫描 workspace/plugins/ 下的插件目录，动态加载/卸载插件工具与知识包

插件目录结构：
    workspace/plugins/<plugin_id>/
    ├── plugin.json   # 元数据：name/version/description/author/enabled/source/builtin/created_at
    ├── skill.md      # 可选：知识包（供技能路由注入提示词）
    └── tools.py      # 可选：用 app.tools.registry 的 @tool 装饰器注册的工具

内置插件（builtin=true）与用户插件同目录同格式，由 app/plugins_seed/ 出厂模板
在首次启动时落盘（ensure_builtin_plugins）；工具注册走同一条动态加载链。

安全约定：
- 导入/新建的插件默认 enabled=false，需用户在插件管理页审查代码后手动启用
- tools.py 仅在插件启用时才被加载执行
"""
import ast
import importlib.util
import json
import re
import shutil
import sys
import time
from pathlib import Path

from app.logger import logger
from app.tools.registry import TOOL_REGISTRY, WORKSPACE_DIR

PLUGINS_DIR = WORKSPACE_DIR / "plugins"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,49}$")

# 插件 id -> 该插件注册的工具名列表（用于禁用时注销）
_PLUGIN_TOOL_NAMES: dict = {}
# 插件 id -> 加载错误信息（scan 时展示）
_PLUGIN_LOAD_ERRORS: dict = {}


# ---------- 元数据 ----------

def _validate_id(plugin_id: str):
    if not _ID_RE.match(plugin_id or ""):
        raise ValueError(
            f"插件 id 不合法: {plugin_id!r}（仅允许小写字母/数字/中划线/下划线，2-50 字符）")


def _plugin_dir(plugin_id: str) -> Path:
    _validate_id(plugin_id)
    return PLUGINS_DIR / plugin_id


def _read_manifest(pdir: Path) -> dict:
    mf = pdir / "plugin.json"
    if mf.exists():
        try:
            return json.loads(mf.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("插件 manifest 解析失败 %s: %s", mf, e)
    return {}


def _write_manifest(pdir: Path, data: dict):
    (pdir / "plugin.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _heal_manifest(pdir: Path) -> dict:
    """无 plugin.json 的手工插件目录自动生成默认 manifest（默认启用）"""
    mf = _read_manifest(pdir)
    if mf:
        return mf
    mf = {
        "id": pdir.name,
        "name": pdir.name,
        "version": "1.0.0",
        "description": "",
        "author": "",
        "enabled": True,
        "source": "manual",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _write_manifest(pdir, mf)
    return mf


def scan_plugins() -> list:
    """扫描全部插件（含禁用），按创建时间倒序"""
    plugins = []
    if not PLUGINS_DIR.exists():
        return plugins
    for pdir in sorted(PLUGINS_DIR.iterdir()):
        if not pdir.is_dir():
            continue
        mf = _heal_manifest(pdir)
        plugins.append({
            "id": pdir.name,
            "name": mf.get("name") or pdir.name,
            "version": mf.get("version", "1.0.0"),
            "description": mf.get("description", ""),
            "author": mf.get("author", ""),
            "enabled": bool(mf.get("enabled", True)),
            "source": mf.get("source", "manual"),
            "builtin": bool(mf.get("builtin", False)),
            "created_at": mf.get("created_at", ""),
            "has_skill": (pdir / "skill.md").exists(),
            "has_tools": (pdir / "tools.py").exists(),
            "tools": mf["tools"] if mf.get("builtin") else _PLUGIN_TOOL_NAMES.get(pdir.name, []),
            "load_error": _PLUGIN_LOAD_ERRORS.get(pdir.name, ""),
        })
    plugins.sort(key=lambda p: p["created_at"], reverse=True)
    plugins.sort(key=lambda p: not p["builtin"])  # 内置插件排序靠前（稳定排序）
    return plugins


def get_plugin(plugin_id: str) -> dict:
    for p in scan_plugins():
        if p["id"] == plugin_id:
            return p
    raise ValueError(f"插件不存在: {plugin_id}")


# ---------- 工具动态加载 / 卸载 ----------

def _load_plugin_tools(plugin_id: str):
    """加载插件 tools.py：模块内 @tool 装饰器副作用完成注册，记录本插件注册的工具名"""
    pdir = _plugin_dir(plugin_id)
    tools_py = pdir / "tools.py"
    if not tools_py.exists():
        return
    before = set(TOOL_REGISTRY.keys())
    mod_name = f"customer_plugin_{plugin_id.replace('-', '_')}"
    sys.modules.pop(mod_name, None)  # 重复启用时强制重新执行模块
    try:
        spec = importlib.util.spec_from_file_location(mod_name, tools_py)
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
    except Exception as e:
        # 回滚本次部分注册，避免残留半个插件的工具
        for name in set(TOOL_REGISTRY.keys()) - before:
            TOOL_REGISTRY.pop(name, None)
        sys.modules.pop(mod_name, None)
        raise RuntimeError(f"插件 {plugin_id} 的 tools.py 加载失败: {e}")
    new_tools = set(TOOL_REGISTRY.keys()) - before
    # 工具名冲突检测：插件不得覆盖已存在的工具（内置或其他插件）
    overwritten = [n for n in new_tools if n in before]
    if overwritten:
        for name in new_tools:
            TOOL_REGISTRY.pop(name, None)
        raise RuntimeError(f"插件 {plugin_id} 工具名与现有工具冲突: {overwritten}")
    _PLUGIN_TOOL_NAMES[plugin_id] = sorted(new_tools)
    _PLUGIN_LOAD_ERRORS.pop(plugin_id, None)
    logger.info("插件 %s 已加载工具: %s", plugin_id, new_tools or "（无工具）")


def _unload_plugin_tools(plugin_id: str):
    for name in _PLUGIN_TOOL_NAMES.pop(plugin_id, []):
        TOOL_REGISTRY.pop(name, None)
    sys.modules.pop(f"customer_plugin_{plugin_id.replace('-', '_')}", None)


# ---------- 内置插件（与用户插件同目录同格式，只读、始终启用、排序靠前） ----------

# 内置插件出厂模板目录：每个子目录即一个完整插件（plugin.json + skill.md + tools.py）。
# workspace/plugins/ 是运行时真源：首次启动整体落盘；后续版本升级时，未被用户修改过的
# 文件跟随模板更新（manifest.seed_hashes 记录落盘时 hash），用户改过的文件永不覆盖。
SEEDS_DIR = Path(__file__).resolve().parent / "plugins_seed"

# 参与 hash 同步的插件文件（plugin.json 的元数据每次直接从模板刷新）
_SEED_FILES = ("skill.md", "tools.py")


def _file_hash(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def ensure_builtin_plugins():
    """把内置插件模板落盘到 workspace/plugins（builtin 标记）

    - 插件目录不存在 -> 整体落盘（skill.md + tools.py + manifest）
    - 已存在 -> 逐文件“未修改才同步”：文件 hash 与落盘记录一致（用户没改过）
      时跟随模板更新；不一致（用户手改过）则保留不动
    - manifest 元数据每次从模板刷新（名称/描述/工具清单等）
    """
    if not SEEDS_DIR.exists():
        return
    for sdir in sorted(SEEDS_DIR.iterdir()):
        if not sdir.is_dir():
            continue
        tmpl_mf = _read_manifest(sdir)
        if not tmpl_mf:
            logger.warning("内置插件模板缺少 plugin.json，跳过: %s", sdir.name)
            continue
        try:
            pid = tmpl_mf.get("id") or sdir.name
            pdir = PLUGINS_DIR / pid
            files = [f for f in _SEED_FILES if (sdir / f).exists()]
            if not pdir.exists():
                pdir.mkdir(parents=True, exist_ok=True)
                for f in files:
                    shutil.copyfile(sdir / f, pdir / f)
                mf = dict(tmpl_mf)
                mf["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                mf["seed_hashes"] = {f: _file_hash(sdir / f) for f in files}
                _write_manifest(pdir, mf)
                continue
            mf = _read_manifest(pdir)
            if not mf.get("builtin"):
                logger.warning("插件目录与内置模板撞名且非内置，跳过: %s", pid)
                continue
            hashes = dict(mf.get("seed_hashes") or {})
            for f in files:
                cur, tmpl_h = pdir / f, _file_hash(sdir / f)
                if not cur.exists():
                    shutil.copyfile(sdir / f, cur)  # 旧版本落盘缺文件（如 tools.py）-> 补齐
                    hashes[f] = tmpl_h
                elif not hashes.get(f):
                    # 旧 manifest 无 hash 记录：与模板一致则登记（后续跟随更新），否则视为用户已修改
                    hashes[f] = tmpl_h if _file_hash(cur) == tmpl_h else _file_hash(cur)
                elif _file_hash(cur) == hashes[f]:
                    if _file_hash(cur) != tmpl_h:  # 未修改 -> 跟随模板更新
                        shutil.copyfile(sdir / f, cur)
                    hashes[f] = tmpl_h
                # 用户修改过（hash 与落盘记录不符）-> 保留不动
            mf.update(tmpl_mf)  # 刷新元数据（不含 created_at，保留原值）
            mf["seed_hashes"] = hashes
            _write_manifest(pdir, mf)
        except Exception as e:
            logger.error("内置插件落盘失败 %s: %s", sdir.name, e)


def load_all_plugins():
    """启动时加载所有启用状态插件的工具（单个失败不影响其他插件与主程序）"""
    ensure_builtin_plugins()
    for p in scan_plugins():
        if not p["enabled"] or not p["has_tools"]:
            continue
        try:
            _load_plugin_tools(p["id"])
        except Exception as e:
            _PLUGIN_LOAD_ERRORS[p["id"]] = str(e)
            logger.error("插件加载失败 %s: %s", p["id"], e)


# ---------- 启停 / 删除 ----------

def set_enabled(plugin_id: str, enabled: bool) -> dict:
    pdir = _plugin_dir(plugin_id)
    if not pdir.exists():
        raise ValueError(f"插件不存在: {plugin_id}")
    mf = _heal_manifest(pdir)
    if mf.get("builtin"):
        raise ValueError("内置插件始终启用，不可停用")
    if enabled and (pdir / "tools.py").exists():
        _load_plugin_tools(plugin_id)  # 加载失败则保持禁用并抛错
    if not enabled:
        _unload_plugin_tools(plugin_id)
        _PLUGIN_LOAD_ERRORS.pop(plugin_id, None)
    mf["enabled"] = enabled
    _write_manifest(pdir, mf)
    logger.info("插件 %s %s", plugin_id, "已启用" if enabled else "已禁用")
    return get_plugin(plugin_id)


def delete_plugin(plugin_id: str):
    pdir = _plugin_dir(plugin_id)
    if not pdir.exists():
        raise ValueError(f"插件不存在: {plugin_id}")
    if _read_manifest(pdir).get("builtin"):
        raise ValueError("内置插件不可删除")
    _unload_plugin_tools(plugin_id)
    _PLUGIN_LOAD_ERRORS.pop(plugin_id, None)
    shutil.rmtree(pdir)
    logger.info("插件 %s 已删除", plugin_id)


# ---------- 创建 ----------

def create_plugin(plugin_id: str, name: str, description: str,
                  skill_md: str = "", tools_py: str = "",
                  source: str = "manual", enabled: bool = True,
                  author: str = "", version: str = "1.0.0") -> dict:
    """创建插件目录与文件。导入/新建来源默认 enabled=False（需人工审查后启用）"""
    pdir = _plugin_dir(plugin_id)
    if pdir.exists():
        raise ValueError(f"插件 id 已存在: {plugin_id}")
    skill_md = (skill_md or "").strip()
    tools_py = (tools_py or "").strip()
    if not skill_md and not tools_py:
        raise ValueError("插件至少需要一个 skill.md（知识包）或 tools.py（工具）")
    if tools_py:
        _validate_tools_py(tools_py)
    pdir.mkdir(parents=True)
    _write_manifest(pdir, {
        "id": plugin_id, "name": name or plugin_id, "version": version,
        "description": description, "author": author,
        "enabled": enabled, "source": source,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    if skill_md:
        (pdir / "skill.md").write_text(skill_md + "\n", encoding="utf-8")
    if tools_py:
        (pdir / "tools.py").write_text(tools_py + "\n", encoding="utf-8")
    if enabled and tools_py:
        try:
            _load_plugin_tools(plugin_id)
        except Exception as e:
            _PLUGIN_LOAD_ERRORS[plugin_id] = str(e)
            mf = _read_manifest(pdir)
            mf["enabled"] = False
            _write_manifest(pdir, mf)
            logger.error("插件 %s 创建后加载失败，已保持禁用: %s", plugin_id, e)
    logger.info("插件 %s 已创建（source=%s, enabled=%s）", plugin_id, source, enabled)
    return get_plugin(plugin_id)


def _validate_tools_py(code: str):
    """手工/导入工具代码的基础校验：语法可解析 + 至少注册了一个工具 + 无工具名冲突"""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise ValueError(f"tools.py 语法错误: 第 {e.lineno} 行 {e.msg}")
    has_tool_deco = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.decorator_list
        for node in ast.walk(tree)
    )
    if not has_tool_deco:
        raise ValueError("tools.py 中未找到任何带 @tool 装饰器的工具函数")
    # 静态提取 @tool(name="xxx") 的工具名做冲突预检
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            if not isinstance(deco, ast.Call):
                continue
            for kw in deco.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                    tname = kw.value.value
                    if tname in TOOL_REGISTRY:
                        raise ValueError(f"工具名 {tname!r} 已被占用，请换一个名称")


# ---------- 知识包接入 ----------

def list_enabled_skills() -> list:
    """返回所有启用插件的知识包（格式与 agent._parse_skill_file 的输出一致）

    内置插件与用户插件同目录同格式，一并返回。
    """
    from app.agent import _parse_skill_file  # 延迟导入避免循环依赖
    skills = []
    for p in scan_plugins():
        if not p["enabled"] or not p["has_skill"]:
            continue
        try:
            skills.append(_parse_skill_file(_plugin_dir(p["id"]) / "skill.md"))
        except Exception as e:
            logger.warning("插件知识包解析失败: %s: %s", p["id"], e)
    return skills


# ---------- 文件读取 / 测试 / 调试 ----------

def read_plugin_files(plugin_id: str) -> dict:
    """读取插件全部文件内容（供审查界面展示）"""
    pdir = _plugin_dir(plugin_id)
    files = {}
    for fname in ("plugin.json", "skill.md", "tools.py"):
        f = pdir / fname
        if f.exists():
            files[fname] = f.read_text(encoding="utf-8")
    return files


def inspect_tools(plugin_id: str) -> list:
    """列出插件的工具定义（名称/label/描述/参数 schema/是否只读），供测试面板使用

    禁用状态的插件临时加载后立即卸载，不在工具池中残留。
    """
    p = get_plugin(plugin_id)
    if not p["has_tools"]:
        return []
    if not p["tools"]:
        _load_plugin_tools(plugin_id)
    try:
        result = []
        for name in _PLUGIN_TOOL_NAMES.get(plugin_id, []):
            t = TOOL_REGISTRY[name]
            result.append({
                "name": name,
                "label": t.get("label", name),
                "description": t.get("description", ""),
                "parameters": t.get("parameters") or {"type": "object", "properties": {}},
                "readonly": t.get("readonly", True),
            })
        return result
    finally:
        if not p["enabled"]:
            _unload_plugin_tools(plugin_id)


def test_tool(plugin_id: str, tool_name: str, args: dict, ctx=None):
    """真实执行插件的一个工具，返回 (ok, payload)

    禁用状态的插件执行期间临时注册工具，执行完立即卸载。
    """
    from app.agent import _exec_tool_call
    p = get_plugin(plugin_id)
    if tool_name not in _PLUGIN_TOOL_NAMES.get(plugin_id, []):
        # 未加载（如刚禁用后直接测试）：临时加载
        if not p["has_tools"]:
            raise ValueError(f"插件 {plugin_id} 没有 tools.py，无可测试的工具")
        _load_plugin_tools(plugin_id)
    try:
        if tool_name not in TOOL_REGISTRY:
            raise ValueError(f"工具 {tool_name} 未注册，插件可能加载失败: "
                             f"{_PLUGIN_LOAD_ERRORS.get(plugin_id, '')}")
        return _exec_tool_call(tool_name, json.dumps(args or {}, ensure_ascii=False), ctx=ctx)
    finally:
        if not p["enabled"]:
            _unload_plugin_tools(plugin_id)


# ---------- 导出 / 导入 ----------

def export_plugin(plugin_id: str, dest: Path) -> Path:
    """把插件目录打包为 zip（导出下载用）"""
    import zipfile
    pdir = _plugin_dir(plugin_id)
    if not pdir.exists():
        raise ValueError(f"插件不存在: {plugin_id}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in pdir.iterdir():
            if f.is_file():
                zf.write(f, f.name)
    return dest


def import_plugin(zip_path: Path) -> dict:
    """从 zip 导入插件（安全校验：zip-slip / 大小 / 结构 / 工具语法与冲突）

    目录冲突自动加后缀；导入后默认禁用（tools.py 有问题时）或按 manifest 启用。
    """
    import zipfile
    if zip_path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("插件包超过 20MB 限制")
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        # zip-slip 防护：拒绝绝对路径与 ..
        for n in names:
            pn = Path(n)
            if pn.is_absolute() or ".." in pn.parts:
                raise ValueError(f"插件包含不安全的路径: {n}")
        file_names = [n for n in names if not n.endswith("/")]
        if not file_names:
            raise ValueError("插件包为空")
        # 结构识别：全部条目在同一个顶层目录下则剥掉该目录
        roots = {Path(n).parts[0] for n in file_names}
        strip = list(roots)[0] if len(roots) == 1 and len(Path(file_names[0]).parts) > 1 else None
        extracted = {}
        for n in file_names:
            rel = Path(n).relative_to(strip) if strip else Path(n)
            if len(rel.parts) != 1:  # 只接受平铺的顶层文件
                continue
            extracted[rel.name] = zf.read(n)
        if not extracted:
            raise ValueError("插件包结构不对：顶层应包含 plugin.json / skill.md / tools.py")
        if not any(k in extracted for k in ("skill.md", "tools.py")):
            raise ValueError("插件包缺少 skill.md 或 tools.py（至少需要其一）")

    manifest = {}
    if "plugin.json" in extracted:
        try:
            manifest = json.loads(extracted["plugin.json"].decode("utf-8"))
        except Exception:
            raise ValueError("plugin.json 不是合法的 JSON")
    pid = str(manifest.get("id") or (strip or zip_path.stem))
    pid = pid.lower().replace(" ", "-")
    _validate_id(pid)
    pdir = PLUGINS_DIR / pid
    n = 2
    while pdir.exists():  # 同名冲突自动加后缀
        pdir = PLUGINS_DIR / f"{pid}-{n}"
        n += 1
    pid = pdir.name

    tools_py = extracted.get("tools.py", b"").decode("utf-8", errors="replace")
    skill_md = extracted.get("skill.md", b"").decode("utf-8", errors="replace")
    if tools_py:
        _validate_tools_py(tools_py)

    enabled = bool(manifest.get("enabled", False))
    pdir.mkdir(parents=True)
    _write_manifest(pdir, {
        "id": pid,
        "name": manifest.get("name") or pid,
        "version": manifest.get("version", "1.0.0"),
        "description": manifest.get("description", ""),
        "author": manifest.get("author", ""),
        "enabled": enabled,
        "source": "imported",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    if skill_md.strip():
        (pdir / "skill.md").write_text(skill_md, encoding="utf-8")
    if tools_py.strip():
        (pdir / "tools.py").write_text(tools_py, encoding="utf-8")
        if enabled:  # manifest 声明启用：先验证能否加载，失败则保持禁用
            try:
                _load_plugin_tools(pid)
            except Exception as e:
                _PLUGIN_LOAD_ERRORS[pid] = str(e)
                mf = _read_manifest(pdir)
                mf["enabled"] = False
                _write_manifest(pdir, mf)
    logger.info("插件 %s 从 %s 导入（enabled=%s）", pid, zip_path.name, enabled)
    return get_plugin(pid)
