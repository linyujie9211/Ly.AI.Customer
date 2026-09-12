"""路径工具：定位项目根目录与运行时工作区（开发模式取 app/ 上级，打包模式取 exe 同级目录）"""
import sys
from pathlib import Path


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


# 运行时工作区：所有后端生成的文件统一落在此目录下，子目录区分用途
WORKSPACE_DIR = project_root() / "workspace"
DATA_DIR = WORKSPACE_DIR / "data"           # SQLite 数据库
LOG_DIR = WORKSPACE_DIR / "logs"            # 日志
KNOWLEDGE_BASE_DIR = WORKSPACE_DIR / "knowledge_base"  # 本地知识库
