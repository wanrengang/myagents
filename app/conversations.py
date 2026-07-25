"""会话元数据库（独立于 LangGraph checkpointer）。

checkpointer（demo.db）负责"对话状态本身"（消息、工具调用中间态），
本模块负责"会话的清单信息"：标题、预览、归属员工、时间戳、消息数——
也就是前端"历史对话"侧栏要展示的元数据。

两者通过 conversation_id（= checkpointer 的 thread_id）关联。
本库用独立 sqlite 文件，避免与 LangGraph 的 checkpointer 并发读写相互干扰。
"""
import sqlite3
import time
from pathlib import Path

from app.paths import db_path

ROOT = Path(__file__).resolve().parent.parent
DB = db_path("conversations.db")


def _conn():
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    con.execute(
        """CREATE TABLE IF NOT EXISTS conversations (
            conv_id      TEXT PRIMARY KEY,
            employee_id TEXT NOT NULL,
            user_id      TEXT DEFAULT 'default',
            title        TEXT DEFAULT '',
            preview      TEXT DEFAULT '',
            message_count INTEGER DEFAULT 0,
            created_at   TEXT,
            updated_at   TEXT
        )"""
    )
    # 老库迁移：补 user_id 列
    cols = [r[1] for r in con.execute("PRAGMA table_info(conversations)")]
    if "user_id" not in cols:
        con.execute("ALTER TABLE conversations ADD COLUMN user_id TEXT DEFAULT 'default'")
    # 软删迁移：补 deleted_at 列（NULL=未删除）
    if "deleted_at" not in cols:
        con.execute("ALTER TABLE conversations ADD COLUMN deleted_at TEXT")
    return con


def create(conv_id: str, employee_id: str, title: str = "", preview: str = "",
           count: int = 0, user_id: str = "default"):
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _conn() as con:
        con.execute(
            "INSERT INTO conversations "
            "(conv_id, employee_id, user_id, title, preview, message_count, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(conv_id) DO UPDATE SET deleted_at=NULL, updated_at=excluded.updated_at",
            (conv_id, employee_id, user_id, title, preview, count, now, now),
        )


def exists(conv_id: str) -> bool:
    with _conn() as con:
        return con.execute("SELECT 1 FROM conversations WHERE conv_id=? AND deleted_at IS NULL", (conv_id,)).fetchone() is not None


def touch(conv_id: str, *, title: str | None = None, preview: str | None = None, bump: int = 0):
    """更新会话清单。title 仅在当前为空时写入（首条消息定标题，后续不覆盖）。"""
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _conn() as con:
        if title is not None:
            con.execute(
                "UPDATE conversations SET title=?, updated_at=? "
                "WHERE conv_id=? AND (title='' OR title IS NULL)",
                (title, now, conv_id),
            )
        if preview is not None:
            con.execute(
                "UPDATE conversations SET preview=?, updated_at=? WHERE conv_id=?",
                (preview, now, conv_id),
            )
        if bump:
            con.execute(
                "UPDATE conversations SET message_count=message_count+?, updated_at=? WHERE conv_id=?",
                (bump, now, conv_id),
            )


def _where(employee_id=None, user_id=None):
    sql = "WHERE deleted_at IS NULL"; params = []
    if employee_id: sql += " AND employee_id=?"; params.append(employee_id)
    if user_id: sql += " AND user_id=?"; params.append(user_id)
    return sql, params


def list_for(employee_id: str | None = None, user_id: str | None = None,
             limit: int | None = None) -> list[dict]:
    """会话清单（按员工/用户过滤；limit 限制条数，用于侧栏最近会话）。"""
    with _conn() as con:
        wh, params = _where(employee_id, user_id)
        sql = f"SELECT * FROM conversations {wh} ORDER BY updated_at DESC, created_at DESC, conv_id DESC"
        if limit:
            sql += " LIMIT ?"; params.append(limit)
        rows = con.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def list_paged(employee_id: str | None = None, user_id: str | None = None,
               page: int = 1, page_size: int = 10) -> dict:
    """分页会话清单，返回 {items, total, page, page_size}。"""
    page = max(1, page)
    with _conn() as con:
        sql, params = _where(employee_id, user_id)
        total = con.execute(f"SELECT COUNT(*) FROM conversations {sql}", params).fetchone()[0]
        full = f"SELECT * FROM conversations {sql} ORDER BY updated_at DESC, created_at DESC, conv_id DESC LIMIT ? OFFSET ?"
        rows = con.execute(full, params + [page_size, (page - 1) * page_size]).fetchall()
    return {"items": [dict(r) for r in rows], "total": total,
            "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size}


def set_title(conv_id: str, title: str):
    """强制更新会话标题（用于 AI 提炼标题覆盖首句截断）。"""
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _conn() as con:
        con.execute("UPDATE conversations SET title=?, updated_at=? WHERE conv_id=?",
                    (title[:40], now, conv_id))


def get(conv_id: str) -> dict | None:
    with _conn() as con:
        r = con.execute("SELECT * FROM conversations WHERE conv_id=? AND deleted_at IS NULL", (conv_id,)).fetchone()
    return dict(r) if r else None


def delete(conv_id: str) -> bool:
    """软删会话元数据（deleted_at 标记，记录与对话正文均保留）。返回是否有行受影响。"""
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _conn() as con:
        cur = con.cursor()
        cur.execute(
            "UPDATE conversations SET deleted_at=? WHERE conv_id=? AND deleted_at IS NULL",
            (now, conv_id))
        ok = cur.rowcount > 0
        con.commit()
    return ok


def all_conv_ids() -> list[str]:
    with _conn() as con:
        return [r[0] for r in con.execute("SELECT conv_id FROM conversations").fetchall()]
