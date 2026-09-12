"""应用入口：纯 Web 模式（FastAPI + uvicorn）"""
import sys
import os

# 项目根目录加入路径
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def run_web():
    """启动 FastAPI 服务"""
    import uvicorn
    from app.server import app
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    run_web()
