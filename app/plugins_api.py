"""插件管理 API：列表 / 新建 / 启停 / 删除 / 文件查看 / 上传导入 / 导出下载 / 工具测试"""
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

from app.logger import logger
from app import plugin_manager as pm

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


class PluginCreateIn(BaseModel):
    plugin_id: str
    name: str = ""
    description: str = ""
    skill_md: str = ""
    tools_py: str = ""
    enabled: bool = False
    author: str = ""
    version: str = "1.0.0"


class PluginTestIn(BaseModel):
    tool_name: str
    args: dict = {}


@router.get("")
def list_plugins():
    return pm.scan_plugins()


@router.post("")
def create_plugin(data: PluginCreateIn):
    """手动新建插件（默认禁用，审查后启用）"""
    try:
        plugin = pm.create_plugin(
            plugin_id=(data.plugin_id or "").strip().lower(),
            name=data.name, description=data.description,
            skill_md=data.skill_md, tools_py=data.tools_py,
            source="manual", enabled=data.enabled,
            author=data.author, version=data.version,
        )
        return {**plugin, "files": pm.read_plugin_files(plugin["id"])}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("插件创建异常: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建失败: {e}")


@router.get("/{plugin_id}/files")
def plugin_files(plugin_id: str):
    try:
        return pm.read_plugin_files(plugin_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{plugin_id}/toggle")
def toggle_plugin(plugin_id: str, enabled: bool = True):
    try:
        return pm.set_enabled(plugin_id, enabled)
    except (ValueError, RuntimeError) as e:
        logger.warning("插件启停失败 %s: %s", plugin_id, e)
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{plugin_id}")
def remove_plugin(plugin_id: str):
    try:
        pm.delete_plugin(plugin_id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/import")
async def import_plugin(file: UploadFile):
    """上传 zip 导入插件（默认禁用，审查后启用）"""
    import os
    tmp = Path(tempfile.gettempdir()) / f"customer_import_{os.getpid()}_{file.filename or 'plugin.zip'}"
    try:
        content = await file.read()
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="插件包超过 20MB 限制")
        tmp.write_bytes(content)
        try:
            plugin = pm.import_plugin(tmp)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error("插件导入异常: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail=f"导入失败: {e}")
        return {**plugin, "files": pm.read_plugin_files(plugin["id"])}
    finally:
        tmp.unlink(missing_ok=True)


@router.get("/{plugin_id}/export")
def export_plugin(plugin_id: str):
    """导出插件为 zip 下载"""
    try:
        dest = pm.export_plugin(plugin_id, Path(tempfile.gettempdir()) / f"{plugin_id}.zip")
        return FileResponse(
            dest, media_type="application/zip",
            filename=f"{plugin_id}.zip",
            headers={"Cache-Control": "no-store"},
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{plugin_id}/inspect")
def inspect_plugin_tools(plugin_id: str):
    """列出插件工具定义（含参数 schema），供测试面板使用"""
    try:
        return {"tools": pm.inspect_tools(plugin_id)}
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{plugin_id}/test")
def test_plugin_tool(plugin_id: str, data: PluginTestIn):
    """真实执行插件的一个工具（禁用插件临时加载、执行完立即卸载）"""
    if not (data.tool_name or "").strip():
        raise HTTPException(status_code=400, detail="缺少 tool_name")
    try:
        ok, payload = pm.test_tool(plugin_id, data.tool_name.strip(), data.args)
        return {"ok": ok, "result": payload}
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
