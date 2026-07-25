"""测试夹具：每个测试用独立的临时数据库，互不污染、不碰真实 catalog.db/conversations.db。"""
import pytest

from app import catalog, conversations


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "DB", tmp_path / "catalog.db")
    monkeypatch.setattr(conversations, "DB", tmp_path / "conversations.db")
    catalog.init()  # 建目录库表（conversations._conn 会自动建会话表）
    yield
