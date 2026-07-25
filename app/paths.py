"""统一的数据目录与数据库路径解析。

本地默认数据目录 = 项目根 (ROOT)，与历史行为完全一致；
容器化部署可通过环境变量 ``APP_DATA_DIR`` 把 SQLite 库指向挂载卷，
从而让 catalog.db / conversations.db / demo.db / store.db / traces.db
在容器重启后依然持久化。
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("APP_DATA_DIR", str(ROOT))).resolve()

# 全部需要持久化的 SQLite 库文件名（备份脚本也用这一份清单）
DB_FILES = ("catalog.db", "conversations.db", "demo.db", "store.db", "traces.db")


def db_path(name: str) -> Path:
    """返回某个数据库文件的绝对路径（受 APP_DATA_DIR 控制）。"""
    return DATA_DIR / name
