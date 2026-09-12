"""统一日志模块：写入运行时工作区 workspace/logs 目录，同时输出到控制台"""
import logging
import sys
from logging.handlers import RotatingFileHandler

from app.paths import LOG_DIR

LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "app.log"


def _setup() -> logging.Logger:
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("ly_ai_customer")
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        return logger

    # 文件 handler（滚动，单文件 5MB，保留 3 个）
    fh = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    logger.addHandler(fh)

    # 控制台 handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)
    logger.addHandler(ch)

    return logger


logger = _setup()
