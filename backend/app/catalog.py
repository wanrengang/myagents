"""数字员工目录库：把"写死的"员工/技能/工具/知识库/SOP/连接器配置入库，
支持页面化配置。SQLite 单文件 catalog.db（与对话 checkpointer 分离）。

表：
- employees / skills / tools / knowledge_bases / kb_entries / sops / connectors
- 关联表：employee_skills / employee_tools / employee_kbs / employee_sops / employee_connectors

init()           建表（幂等）
seed_if_empty()  首次启动把现有两个员工（小苏、小数）及其技能/工具/知识库/
                连接器/SOP 原样种子进库；已存在则跳过。运行时以本库为准，
                employees/*.yaml 仅作种子来源。
list_employees_meta / get_employee_config / get_full_employee / catalog
create_employee / update_employee / delete_employee
"""
import json
import os
import re
import sqlite3
import time
from pathlib import Path

from app.paths import db_path
from app.spec import load_spec  # 仅种子阶段用于读取 yaml 的人设等字段

ROOT = Path(__file__).resolve().parent.parent
DB = db_path("catalog.db")


def _conn():
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    return con


def init():
    """建表（幂等）。"""
    con = _conn()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS skills(
      id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, dir TEXT);
    CREATE TABLE IF NOT EXISTS tools(
      id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, source TEXT, needs_approval TEXT);
    CREATE TABLE IF NOT EXISTS knowledge_bases(
      id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT);
    CREATE TABLE IF NOT EXISTS kb_entries(
      id TEXT PRIMARY KEY, kb_id TEXT NOT NULL, title TEXT, keywords TEXT, content TEXT);
    CREATE TABLE IF NOT EXISTS sops(
      id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, content TEXT);
    CREATE TABLE IF NOT EXISTS connectors(
      id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, config TEXT);
    CREATE TABLE IF NOT EXISTS employees(
      id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT, model TEXT,
      persona TEXT, backend TEXT DEFAULT 'state', mcp_servers TEXT, interrupt_on TEXT,
      created_at TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS employee_skills(employee_id TEXT, skill_id TEXT, PRIMARY KEY(employee_id, skill_id));
    CREATE TABLE IF NOT EXISTS employee_tools(employee_id TEXT, tool_id TEXT, PRIMARY KEY(employee_id, tool_id));
    CREATE TABLE IF NOT EXISTS employee_kbs(employee_id TEXT, kb_id TEXT, PRIMARY KEY(employee_id, kb_id));
    CREATE TABLE IF NOT EXISTS employee_sops(employee_id TEXT, sop_id TEXT, PRIMARY KEY(employee_id, sop_id));
    CREATE TABLE IF NOT EXISTS employee_connectors(employee_id TEXT, connector_id TEXT, PRIMARY KEY(employee_id, connector_id));
    CREATE TABLE IF NOT EXISTS users(
      id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL, role TEXT DEFAULT 'user',
      status TEXT DEFAULT 'active', tenant_id TEXT DEFAULT 'default',
      created_at TEXT);
    CREATE TABLE IF NOT EXISTS user_employee_assignments(
      user_id TEXT NOT NULL,
      employee_id TEXT NOT NULL,
      granted_by TEXT,
      overrides TEXT,
      created_at TEXT,
      PRIMARY KEY(user_id, employee_id));
    """)
    con.commit()
    _migrate_soft_delete(con)
    _migrate_must_change_password(con)
    _migrate_remove_refund_gate(con)
    con.close()


# 实体表（有独立生命周期，删除走软删）；关联表不加。
# tools 无删除入口，但通用列表查询会遍历它，补列以便统一 deleted_at 过滤。
_SOFT_DELETE_TABLES = (
    "users", "employees", "skills", "tools", "knowledge_bases",
    "kb_entries", "sops", "connectors",
)


def _migrate_soft_delete(con):
    """给实体表补 deleted_at 列（NULL=未删除）。幂等。"""
    for t in _SOFT_DELETE_TABLES:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
        if "deleted_at" not in cols:
            con.execute(f"ALTER TABLE {t} ADD COLUMN deleted_at TEXT")
    con.commit()


def _migrate_must_change_password(con):
    """users 表补 must_change_password 列（1=首登必须改密）。幂等。"""
    cols = [r[1] for r in con.execute("PRAGMA table_info(users)")]
    if "must_change_password" not in cols:
        con.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0")
    con.commit()


def _migrate_remove_refund_gate(con):
    """撤 start_refund 的外层审批 gate（Point2：审批内化进 workflow 状态机）。

    背景：老实现里退款审批由外层 agent 的 interrupt_on 拦截（tools.start_refund
    .needs_approval=["approve","reject"]）。Point2 把审批内化进 refund StateGraph
    的 await_approval 节点（interrupt），外层 gate 必须撤掉，否则双重 interrupt。

    幂等：needs_approval 已为 NULL 时跳过。同时刷新 employees 表的 interrupt_on
    存值（编译时也会实时重算，此处保证 DB 一致，避免管理后台展示陈旧状态）。
    """
    row = con.execute("SELECT needs_approval FROM tools WHERE id='start_refund'").fetchone()
    if not row or not row["needs_approval"]:
        return  # 已撤或工具不存在
    con.execute("UPDATE tools SET needs_approval=NULL WHERE id='start_refund'")
    # 刷新所有挂了 start_refund 的员工的 interrupt_on 存值
    for emp in con.execute(
        "SELECT e.id, e.interrupt_on FROM employees e "
        "JOIN employee_tools et ON et.employee_id=e.id "
        "WHERE et.tool_id='start_refund' AND e.deleted_at IS NULL"
    ).fetchall():
        old = json.loads(emp["interrupt_on"]) if emp["interrupt_on"] else {}
        old.pop("start_refund", None)  # 撤掉外层 gate
        con.execute("UPDATE employees SET interrupt_on=? WHERE id=?",
                    (json.dumps(old, ensure_ascii=False), emp["id"]))
    con.commit()
    print("[migrate] 已撤 start_refund 外层审批 gate（Point2 内化审批）")


# ---------------------------------------------------------------------------
# 用户管理
# ---------------------------------------------------------------------------

def create_user(username: str, password_hash: str, role: str = "user",
                tenant_id: str = "default", user_id: str | None = None) -> str:
    uid = user_id or ("u_" + time.strftime("%Y%m%d%H%M%S"))
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    con = _conn()
    # 软删复活：同名用户曾被软删（username 唯一键仍被占用）→ 重建即复活并更新凭据
    old = con.execute("SELECT id FROM users WHERE username=? AND deleted_at IS NOT NULL",
                      (username,)).fetchone()
    if old:
        con.execute(
            "UPDATE users SET password_hash=?, role=?, status='active', tenant_id=?, deleted_at=NULL "
            "WHERE username=?",
            (password_hash, role, tenant_id, username))
        con.commit(); con.close()
        return old["id"]
    con.execute(
        "INSERT OR IGNORE INTO users(id,username,password_hash,role,status,tenant_id,created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (uid, username, password_hash, role, "active", tenant_id, now))
    con.commit()
    con.close()
    return uid


def get_user(user_id: str) -> dict | None:
    con = _conn()
    r = con.execute("SELECT * FROM users WHERE id=? AND deleted_at IS NULL", (user_id,)).fetchone()
    con.close()
    return dict(r) if r else None


def get_user_by_username(username: str) -> dict | None:
    con = _conn()
    r = con.execute("SELECT * FROM users WHERE username=? AND deleted_at IS NULL", (username,)).fetchone()
    con.close()
    return dict(r) if r else None


def list_users() -> list[dict]:
    con = _conn()
    rows = con.execute("SELECT id,username,role,status,tenant_id,created_at FROM users WHERE deleted_at IS NULL ORDER BY created_at").fetchall()
    con.close()
    return [dict(r) for r in rows]


def list_users_paged(page: int = 1, page_size: int = 10) -> dict:
    """分页查询用户列表，返回 {items, total, page, page_size, pages}。"""
    page = max(1, page)
    con = _conn()
    total = con.execute("SELECT COUNT(*) FROM users WHERE deleted_at IS NULL").fetchone()[0]
    offset = (page - 1) * page_size
    rows = con.execute(
        "SELECT id,username,role,status,tenant_id,created_at FROM users WHERE deleted_at IS NULL ORDER BY created_at LIMIT ? OFFSET ?",
        (page_size, offset)).fetchall()
    con.close()
    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


def update_user(user_id: str, role: str | None = None, status: str | None = None) -> bool:
    con = _conn(); cur = con.cursor()
    if role is not None:
        cur.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
    if status is not None:
        cur.execute("UPDATE users SET status=? WHERE id=?", (status, user_id))
    ok = cur.rowcount > 0
    con.commit(); con.close()
    return ok


def set_password(user_id: str, password_hash: str) -> bool:
    """改密同时清掉 must_change_password 标记。"""
    con = _conn(); cur = con.cursor()
    cur.execute("UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?",
                (password_hash, user_id))
    ok = cur.rowcount > 0
    con.commit(); con.close()
    return ok


def set_must_change_password(user_id: str, flag: bool = True) -> bool:
    con = _conn(); cur = con.cursor()
    cur.execute("UPDATE users SET must_change_password=? WHERE id=?",
                (1 if flag else 0, user_id))
    ok = cur.rowcount > 0
    con.commit(); con.close()
    return ok


def _soft_delete_row(table: str, id_: str, col: str = "id") -> bool:
    """把实体行标记为已删除（软删）。返回是否有行受影响（已删的不重复标记）。"""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    con = _conn(); cur = con.cursor()
    cur.execute(
        f"UPDATE {table} SET deleted_at=? WHERE {col}=? AND deleted_at IS NULL",
        (now, id_))
    ok = cur.rowcount > 0
    con.commit(); con.close()
    return ok


def delete_user(user_id: str) -> bool:
    """软删用户（记录保留，deleted_at 标记）。"""
    return _soft_delete_row("users", user_id)


# ---------------------------------------------------------------------------
# 用户-员工分配（模板 + 每用户覆盖）
# ---------------------------------------------------------------------------

def assign_employee(user_id: str, emp_id: str, overrides: dict | None = None,
                    granted_by: str | None = None) -> bool:
    """分配一个员工给用户（幂等，重复调用覆盖 overrides）。overrides 形如
    {"add":{...},"remove":{...}}，仅作用该用户，不影响模板。"""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    con = _conn()
    con.execute(
        "INSERT OR REPLACE INTO user_employee_assignments"
        "(user_id,employee_id,granted_by,overrides,created_at) VALUES(?,?,?,?,?)",
        (user_id, emp_id, granted_by,
         json.dumps(overrides or {}, ensure_ascii=False), now))
    con.commit()
    con.close()
    return True


def unassign_employee(user_id: str, emp_id: str) -> bool:
    con = _conn()
    cur = con.cursor()
    cur.execute(
        "DELETE FROM user_employee_assignments WHERE user_id=? AND employee_id=?",
        (user_id, emp_id))
    ok = cur.rowcount > 0
    con.commit()
    con.close()
    return ok


def get_assignment(user_id: str, emp_id: str) -> dict | None:
    con = _conn()
    r = con.execute(
        "SELECT * FROM user_employee_assignments WHERE user_id=? AND employee_id=?",
        (user_id, emp_id)).fetchone()
    con.close()
    if not r:
        return None
    d = dict(r)
    d["overrides"] = json.loads(d["overrides"]) if d["overrides"] else {}
    return d


def list_assignments(user_id: str) -> list[dict]:
    con = _conn()
    rows = con.execute(
        "SELECT * FROM user_employee_assignments WHERE user_id=?", (user_id,)).fetchall()
    con.close()
    return [{**dict(r), "overrides": json.loads(r["overrides"]) if r["overrides"] else {}}
            for r in rows]


def set_assignment_overrides(user_id: str, emp_id: str, overrides: dict) -> bool:
    """更新某用户对该员工的覆盖（仅改分配行，不改模板）。"""
    con = _conn()
    cur = con.cursor()
    cur.execute(
        "UPDATE user_employee_assignments SET overrides=? "
        "WHERE user_id=? AND employee_id=?",
        (json.dumps(overrides, ensure_ascii=False), user_id, emp_id))
    ok = cur.rowcount > 0
    con.commit()
    con.close()
    return ok


def assigned_employee_ids(user_id: str) -> list[str]:
    con = _conn()
    out = [r[0] for r in con.execute(
        "SELECT employee_id FROM user_employee_assignments WHERE user_id=?", (user_id,))]
    con.close()
    return out


def list_user_ids_with_emp(emp_id: str) -> list[str]:
    """返回分配了该员工的所有用户（员工模板变更时用于清缓存）。"""
    con = _conn()
    out = [r[0] for r in con.execute(
        "SELECT user_id FROM user_employee_assignments WHERE employee_id=?", (emp_id,))]
    con.close()
    return out


def seed_assignments_if_empty():
    """启动一次性种子：若某已有用户 0 分配，则授予全部现有员工（overrides 空=用模板）。
    保证 demo 不崩；新用户默认 0 分配，由 admin 显式分配。幂等。"""
    users = list_users()
    emps = list_employees_meta()
    if not users or not emps:
        return
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    con = _conn()
    cur = con.cursor()
    for u in users:
        cnt = cur.execute(
            "SELECT COUNT(*) FROM user_employee_assignments WHERE user_id=?",
            (u["id"],)).fetchone()[0]
        if cnt == 0:
            for e in emps:
                cur.execute(
                    "INSERT OR IGNORE INTO user_employee_assignments"
                    "(user_id,employee_id,granted_by,overrides,created_at) VALUES(?,?,?,?,?)",
                    (u["id"], e["id"], "u_admin", "{}", now))
    con.commit()
    con.close()


def seed_admin_if_empty():
    """确保默认管理员账号可用（.env ADMIN_USER/ADMIN_PASS，默认 admin/admin123）。

    - 首次启动（无任何用户）创建默认管理员；
    - 非首次：若默认管理员已存在但密码与 ADMIN_PASS 不符
      （例如从旧 dev 库恢复 / 手动改过导致不一致），重置对齐为 ADMIN_PASS。
      该自愈仅作用于自动种子出的默认管理员，不影响后来新建的其他账号。
    - ADMIN_PASS 仍为文档默认 'admin123' 时，标记首登强制改密。
    """
    from app.auth import hash_password, verify_password
    import os
    username = os.environ.get("ADMIN_USER", "admin")
    password = os.environ.get("ADMIN_PASS", "admin123")

    con = _conn()
    empty = con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    con.close()

    if empty and not get_user_by_username(username):
        uid = create_user(username, hash_password(password), role="admin",
                          user_id="u_admin")
        print(f"[seed] 已创建初始管理员：{username} / {password}（首次登录须修改密码）")
        if password == "admin123":
            set_must_change_password(uid, True)
        return

    # 非首次启动：修复默认管理员密码（若与 ADMIN_PASS 不一致）
    u = get_user_by_username(username)
    if u and not verify_password(password, u["password_hash"]):
        set_password(u["id"], hash_password(password))
        print("[seed] 默认管理员密码已与 ADMIN_PASS 对齐（重置）")
        if password == "admin123":
            set_must_change_password(u["id"], True)


def flag_default_admin_password():
    """启动检查：若 admin 仍在用默认密码 admin123，标记首登强制改密。幂等。"""
    import os
    from app.auth import verify_password
    u = get_user_by_username(os.environ.get("ADMIN_USER", "admin"))
    if u and not u.get("must_change_password") and verify_password("admin123", u["password_hash"]):
        set_must_change_password(u["id"], True)
        print("[security] admin 仍为默认密码，已标记首登强制改密")


def _skill_desc(skill_dir: Path) -> str:
    md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    return next((l.split(":", 1)[1].strip() for l in md.splitlines()
                 if l.startswith("description:")), "")


def seed_if_empty():
    """把现有两个员工 + 目录种子进库（仅当 employees 为空时）。"""
    con = _conn()
    cur = con.cursor()
    if cur.execute("SELECT COUNT(*) FROM employees").fetchone()[0] > 0:
        con.close()
        return
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    # --- skills（扫描 skills/ 目录）---
    for sd in sorted((ROOT / "skills").glob("*/")):
        sid = sd.name
        cur.execute("INSERT OR IGNORE INTO skills VALUES(?,?,?,?)",
                    (sid, sid, _skill_desc(sd), f"skills/{sid}"))

    # --- tools（本地工具注册表）---
    tools = [
        ("kb_search", "知识库检索", "检索产品 FAQ 知识库", "local", None),
        ("create_ticket", "工单登记", "登记客服工单", "local", None),
        ("start_refund", "退款流程", "发起退款（需人工审批）", "local", json.dumps(["approve", "reject"])),
    ]
    for t in tools:
        cur.execute("INSERT OR IGNORE INTO tools VALUES(?,?,?,?,?)", t)

    # --- knowledge base + entries（源自 app/tools/kb.py 的 FAQ）---
    from app.tools.kb import FAQ
    cur.execute("INSERT OR IGNORE INTO knowledge_bases VALUES(?,?,?)",
                ("kb_product", "产品知识库", "智选智能硬件产品 FAQ"))
    for it in FAQ:
        cur.execute("INSERT OR IGNORE INTO kb_entries VALUES(?,?,?,?,?)",
                    (it["id"], "kb_product", it["title"],
                     json.dumps(it["keywords"], ensure_ascii=False), it["content"]))

    # --- sops（可勾选流程文档，对齐原 yaml 的 sop 字段语义）---
    sops = [
        ("sop_refund", "退款流程（刚性）", "用户要求退款时调用 start_refund，自动进入人工审批",
         "## 退款流程（刚性）\n用户要求退款退货时，调用 start_refund 工具发起退款流程。"
         "固定三步：校验订单 → 计算金额 → 审批 → 生成退款单。\n\n"
         "### 执行路径\n"
         "1. **校验订单**：系统自动检查订单是否存在、已签收、签收 7 天内\n"
         "2. **计算金额**：按订单实际支付金额计算退款\n"
         "3. **人工审批**：流程卡在审批节点，等待管理员批准或拒绝\n"
         "4. **生成退款单**：审批通过后自动生成退款单号\n\n"
         "### 退款条件\n"
         "- 仅已签收订单可退款\n"
         "- 签收超过 7 天不可无理由退款（可走售后维修）\n"
         "- 运输中订单请先签收后再申请退款\n\n"
         "### 注意事项\n"
         "- 退款将原路返回，3-5 个工作日到账\n"
         "- 审批不可跳过，必须等待人工处理"),
        ("sop_complaint", "投诉处理（软性）", "用户表达不满时按 complaint-handling 技能规程执行",
         "## 投诉处理（软性）\n用户表达不满或投诉时，必须先用 read_file 读取 "
         "/skills/complaint-handling/SKILL.md，然后严格按其中的规程执行。\n\n"
         "### 执行步骤（按顺序，不可跳过）\n\n"
         "#### 步骤 1：安抚\n"
         "先共情一句话再处理，不辩解、不推责。\n"
         "- 句式参考：「非常抱歉给您带来了不便」「我完全理解您的心情」\n"
         "- 绝对禁止：「这是正常的」「您可能没看清楚」「其他用户都没问题」\n\n"
         "#### 步骤 2：核实\n"
         "- 先问订单号（如未提供），用 order_query 查订单详情\n"
         "- 用 kb_search 查该产品是否有已知问题或常见故障处理\n"
         "- 必要时查 customer_profile 了解用户等级（VIP 优先处理）\n\n"
         "#### 步骤 3：分类定级并登记工单\n"
         "紧急度判断标准：\n"
         "- urgent（安全风险/大面积故障/VIP 客诉）→ 2 小时响应\n"
         "- high（功能故障/严重影响使用）→ 24 小时响应\n"
         "- normal（一般不满/轻微问题/咨询类）→ 48 小时响应\n\n"
         "#### 步骤 4：给出答复\n"
         "告知用户工单号、预计响应时间、一个当下可执行的临时方案\n\n"
         "### 禁忌\n"
         "- 不要在未登记工单前承诺赔偿金额\n"
         "- 不要与用户争辩\n"
         "- 不要把用户晾着去查东西"),
    ]
    for s in sops:
        cur.execute("INSERT OR IGNORE INTO sops VALUES(?,?,?,?)", s)

    # --- connectors（MCP 连接器，如 CRM）---
    cur.execute("INSERT OR IGNORE INTO connectors VALUES(?,?,?,?)",
                ("crm", "CRM 连接器", "订单查询 MCP（stdio）",
                 json.dumps({"transport": "stdio", "command": "${PYTHON_BIN}",
                             "args": ["app/connectors/crm_server.py"]}, ensure_ascii=False)))

    # --- employees（人设/后端/中断策略从 yaml 读取）---
    seeds = {
        "xiaosu": dict(
            skills=["product-faq", "complaint-handling"],
            tools=["kb_search", "create_ticket", "start_refund"],
            kbs=["kb_product"], sops=["sop_refund", "sop_complaint"], cons=["crm"]),
        "xiaoshu": dict(
            skills=["data-analysis"], tools=[], kbs=[], sops=[], cons=[]),
        "xiaoxiao": dict(
            skills=["enterprise-sales"],
            tools=["kb_search", "generate_solution_doc", "query_product_wiki",
                   "list_product_catalog", "bocha_search"],
            kbs=["kb_product"], sops=[], cons=["crm"]),
    }
    for emp_id, sel in seeds.items():
        spec = load_spec(str(ROOT / "app" / "employees" / f"{emp_id}.yaml"))
        model = re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), m.group(0)), spec.model)
        cur.execute("INSERT INTO employees VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (emp_id, spec.name, spec.role, model, spec.persona, spec.backend,
                     json.dumps(spec.mcp_servers, ensure_ascii=False),
                     json.dumps(spec.interrupt_on, ensure_ascii=False), now, now))
        for s in sel["skills"]:
            cur.execute("INSERT OR IGNORE INTO employee_skills VALUES(?,?)", (emp_id, s))
        for t in sel["tools"]:
            cur.execute("INSERT OR IGNORE INTO employee_tools VALUES(?,?)", (emp_id, t))
        for k in sel["kbs"]:
            cur.execute("INSERT OR IGNORE INTO employee_kbs VALUES(?,?)", (emp_id, k))
        for s in sel["sops"]:
            cur.execute("INSERT OR IGNORE INTO employee_sops VALUES(?,?)", (emp_id, s))
        for c in sel["cons"]:
            cur.execute("INSERT OR IGNORE INTO employee_connectors VALUES(?,?)", (emp_id, c))
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------

def list_employees_meta() -> list[dict]:
    con = _conn()
    rows = con.execute(
        "SELECT id,name,role,model,backend FROM employees WHERE deleted_at IS NULL ORDER BY created_at").fetchall()
    out = [dict(r) for r in rows]
    con.close()
    return out


def _config_from_ids(emp_row: dict, skills: list, tools: list, kbs: list,
                     sops: list, cons: list) -> dict:
    """按一组已选定的资源 id（技能/工具/知识库/SOP/连接器）拼出完整编译配置。
    get_employee_config（纯模板）与 get_effective_config（模板+用户覆盖合并）
    共用此函数：前者传模板 id 列表，后者传合并后的 id 列表。"""
    con = _conn()
    cur = con.cursor()
    # 每个技能的目录（可为相对 ROOT 的路径，也可为绝对路径——支持外部技能）
    skill_dirs = {}
    for sid in skills:
        row = cur.execute("SELECT dir FROM skills WHERE id=? AND deleted_at IS NULL", (sid,)).fetchone()
        if row and row["dir"]:
            skill_dirs[sid] = row["dir"]
    # 知识库条目
    entries = []
    for kb in kbs:
        for e in cur.execute(
                "SELECT id,title,keywords,content FROM kb_entries WHERE kb_id=? AND deleted_at IS NULL", (kb,)):
            entries.append({"id": e["id"], "title": e["title"],
                            "keywords": json.loads(e["keywords"]), "content": e["content"]})
    # SOP 文本（拼接所选流程文档）
    sop_text = ""
    for sid in sops:
        s = cur.execute("SELECT content FROM sops WHERE id=? AND deleted_at IS NULL", (sid,)).fetchone()
        if s and s["content"]:
            sop_text += ("\n\n" if sop_text else "") + s["content"]
    # 连接器 → mcp_servers
    mcp_servers = {}
    for cid in cons:
        c = cur.execute("SELECT config FROM connectors WHERE id=? AND deleted_at IS NULL", (cid,)).fetchone()
        if c and c["config"]:
            mcp_servers[cid] = json.loads(c["config"])
    con.close()
    return {
        "id": emp_row["id"], "name": emp_row["name"], "role": emp_row["role"],
        "model": emp_row["model"], "persona": emp_row["persona"],
        "backend": emp_row["backend"] or "state",
        "interrupt_on": _build_interrupt_on(tools),
        "skills": skills, "tools": tools, "kbs": kbs, "sops": sops, "connectors": cons,
        "kb_entries": entries, "sop_text": sop_text, "mcp_servers": mcp_servers,
        "skill_dirs": skill_dirs,
    }


def get_employee_config(emp_id: str) -> dict | None:
    """返回编译一个员工所需的完整配置（纯模板，不含任何用户覆盖）。"""
    con = _conn()
    cur = con.cursor()
    r = cur.execute("SELECT * FROM employees WHERE id=? AND deleted_at IS NULL", (emp_id,)).fetchone()
    if not r:
        con.close()
        return None
    skills = [x[0] for x in cur.execute(
        "SELECT skill_id FROM employee_skills WHERE employee_id=?", (emp_id,))]
    tools = [x[0] for x in cur.execute(
        "SELECT tool_id FROM employee_tools WHERE employee_id=?", (emp_id,))]
    kbs = [x[0] for x in cur.execute(
        "SELECT kb_id FROM employee_kbs WHERE employee_id=?", (emp_id,))]
    sops = [x[0] for x in cur.execute(
        "SELECT sop_id FROM employee_sops WHERE employee_id=?", (emp_id,))]
    cons = [x[0] for x in cur.execute(
        "SELECT connector_id FROM employee_connectors WHERE employee_id=?", (emp_id,))]
    con.close()
    return _config_from_ids(r, skills, tools, kbs, sops, cons)


def get_effective_config(user_id: str, emp_id: str) -> dict | None:
    """返回某用户视角下该员工的有效配置 = 模板基础 ∪ add − remove。
    若用户未分配该员工，返回纯模板（get_employee_config），保证对话不崩。"""
    base = get_employee_config(emp_id)
    if not base:
        return None
    asg = get_assignment(user_id, emp_id)
    if not asg:
        return base
    ov = asg.get("overrides") or {}
    add = ov.get("add", {}) or {}
    remove = ov.get("remove", {}) or {}

    def merge(base_list, key):
        a = set(add.get(key, []))
        rm = set(remove.get(key, []))
        # 去掉被移除的 + 追加新增的（去重）
        out = [x for x in base_list if x not in rm]
        existing = set(out)
        for x in a:
            if x not in existing and x not in rm:
                out.append(x)
                existing.add(x)
        return out

    skills = merge(base["skills"], "skills")
    tools = merge(base["tools"], "tools")
    kbs = merge(base["kbs"], "kbs")
    sops = merge(base["sops"], "sops")
    cons = merge(base["connectors"], "connectors")
    return _config_from_ids(base, skills, tools, kbs, sops, cons)


def get_full_employee(emp_id: str) -> dict | None:
    """get_employee_config + 各选中项的展示名（供管理页回显）。"""
    cfg = get_employee_config(emp_id)
    if not cfg:
        return None
    con = _conn()
    cur = con.cursor()

    def names(table):
        return {x["id"]: x["name"] for x in
                cur.execute(f"SELECT id,name FROM {table} WHERE deleted_at IS NULL")}
    cfg["skill_names"] = names("skills")
    cfg["tool_names"] = names("tools")
    cfg["kb_names"] = names("knowledge_bases")
    cfg["sop_names"] = names("sops")
    cfg["connector_names"] = names("connectors")
    con.close()
    return cfg


def catalog() -> dict:
    """返回管理页可用的全部目录（技能/工具/知识库/SOP/连接器）。"""
    con = _conn()
    cur = con.cursor()

    def allrows(table):
        return [dict(r) for r in cur.execute(f"SELECT * FROM {table} WHERE deleted_at IS NULL")]

    out = {
        "skills": [{"id": s["id"], "name": s["name"], "description": s["description"],
                    "dir": s["dir"], "is_custom": bool(s["dir"] and s["dir"].startswith("skills-custom/"))}
                   for s in allrows("skills")],
        "tools": [{"id": t["id"], "name": t["name"], "description": t["description"],
                   "needs_approval": json.loads(t["needs_approval"]) if t["needs_approval"] else None}
                  for t in allrows("tools")],
        "knowledge_bases": [{"id": k["id"], "name": k["name"], "description": k["description"]}
                            for k in allrows("knowledge_bases")],
        "sops": [{"id": s["id"], "name": s["name"], "description": s["description"], "content": s["content"]}
                 for s in allrows("sops")],
        "connectors": [{"id": c["id"], "name": c["name"], "description": c["description"]}
                       for c in allrows("connectors")],
    }
    con.close()
    return out


# ---------------------------------------------------------------------------
# 技能管理（上传/删除）
# ---------------------------------------------------------------------------

def upsert_skill(skill_id: str, name: str, description: str, dir_: str):
    """新增或更新一条技能记录（id 不变则更新 name/description/dir，保留员工关联）。
    软删复活：同名 id 已被软删 → 重建即复活（deleted_at 一并清空）。"""
    con = _conn()
    con.execute(
        "INSERT INTO skills(id,name,description,dir) VALUES(?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, description=excluded.description, "
        "dir=excluded.dir, deleted_at=NULL",
        (skill_id, name, description, dir_))
    con.commit()
    con.close()


def get_skill(skill_id: str) -> dict | None:
    con = _conn()
    r = con.execute("SELECT id,name,description,dir FROM skills WHERE id=? AND deleted_at IS NULL", (skill_id,)).fetchone()
    con.close()
    return dict(r) if r else None


def employees_using_skill(skill_id: str) -> list[str]:
    con = _conn()
    out = [r[0] for r in con.execute(
        "SELECT employee_id FROM employee_skills WHERE skill_id=?", (skill_id,))]
    con.close()
    return out


def delete_skill(skill_id: str):
    """软删技能记录 + 硬删员工关联（关联为配置关系，即时生效；不删目录文件）。"""
    _soft_delete_row("skills", skill_id)
    con = _conn()
    con.execute("DELETE FROM employee_skills WHERE skill_id=?", (skill_id,))
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# 通用：员工关联清理（删除资源时调用，返回受影响员工供 invalidate）
# ---------------------------------------------------------------------------

_LINK_TABLES = {
    "skill": ("employee_skills", "skill_id"),
    "tool": ("employee_tools", "tool_id"),
    "kb": ("employee_kbs", "kb_id"),
    "sop": ("employee_sops", "sop_id"),
    "connector": ("employee_connectors", "connector_id"),
}


def _unlink(kind: str, res_id: str) -> list[str]:
    """删除某资源在员工关联表里的记录，返回受影响员工 id 列表。"""
    table, col = _LINK_TABLES[kind]
    con = _conn()
    cur = con.cursor()
    affected = [r[0] for r in cur.execute(
        f"SELECT employee_id FROM {table} WHERE {col}=?", (res_id,))]
    cur.execute(f"DELETE FROM {table} WHERE {col}=?", (res_id,))
    con.commit()
    con.close()
    return affected


# ---------------------------------------------------------------------------
# 工具管理（工具由代码定义，页面只编辑元信息：description / needs_approval）
# ---------------------------------------------------------------------------

def update_tool(tool_id: str, description: str, needs_approval) -> bool:
    con = _conn()
    cur = con.cursor()
    na = json.dumps(needs_approval, ensure_ascii=False) if needs_approval else None
    cur.execute("UPDATE tools SET description=?, needs_approval=? WHERE id=?",
                (description, na, tool_id))
    ok = cur.rowcount > 0
    con.commit()
    con.close()
    return ok


def employees_using_tool(tool_id: str) -> list[str]:
    return _unlink_view("tool", tool_id)


def _unlink_view(kind: str, res_id: str) -> list[str]:
    """只查不删，供 GET 用。"""
    table, col = _LINK_TABLES[kind]
    con = _conn()
    out = [r[0] for r in con.execute(
        f"SELECT employee_id FROM {table} WHERE {col}=?", (res_id,))]
    con.close()
    return out


# ---------------------------------------------------------------------------
# 知识库 + 条目管理
# ---------------------------------------------------------------------------

def create_kb(kb_id: str, name: str, description: str = "") -> str:
    con = _conn()
    con.execute(
        "INSERT INTO knowledge_bases(id,name,description) VALUES(?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, description=excluded.description, "
        "deleted_at=NULL",  # 软删复活：同 id 重建即复活
        (kb_id, name, description))
    con.commit()
    con.close()
    return kb_id


def update_kb(kb_id: str, name: str, description: str) -> bool:
    con = _conn()
    cur = con.cursor()
    cur.execute("UPDATE knowledge_bases SET name=?, description=? WHERE id=?",
                (name, description, kb_id))
    ok = cur.rowcount > 0
    con.commit()
    con.close()
    return ok


def delete_kb(kb_id: str):
    """软删知识库 + 软删其全部条目 + 硬删员工关联。返回受影响员工。"""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    con = _conn()
    cur = con.cursor()
    affected = [r[0] for r in cur.execute(
        "SELECT employee_id FROM employee_kbs WHERE kb_id=?", (kb_id,))]
    cur.execute("UPDATE knowledge_bases SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                (now, kb_id))
    cur.execute("UPDATE kb_entries SET deleted_at=? WHERE kb_id=? AND deleted_at IS NULL",
                (now, kb_id))
    cur.execute("DELETE FROM employee_kbs WHERE kb_id=?", (kb_id,))
    con.commit()
    con.close()
    return affected


def list_kb_entries(kb_id: str) -> list[dict]:
    con = _conn()
    rows = con.execute("SELECT id,title,keywords,content FROM kb_entries WHERE kb_id=? AND deleted_at IS NULL", (kb_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["keywords"] = json.loads(d["keywords"]) if d["keywords"] else []
        out.append(d)
    con.close()
    return out


def create_kb_entry(kb_id: str, entry_id: str, title: str, keywords: list, content: str) -> str:
    con = _conn()
    con.execute(
        "INSERT OR REPLACE INTO kb_entries(id,kb_id,title,keywords,content) VALUES(?,?,?,?,?)",
        (entry_id, kb_id, title, json.dumps(keywords, ensure_ascii=False), content))
    # OR REPLACE 整行重写，deleted_at 自动回 NULL（软删复活）
    con.commit()
    con.close()
    return entry_id


def update_kb_entry(entry_id: str, title: str, keywords: list, content: str) -> bool:
    con = _conn()
    cur = con.cursor()
    cur.execute("UPDATE kb_entries SET title=?, keywords=?, content=? WHERE id=?",
                (title, json.dumps(keywords, ensure_ascii=False), content, entry_id))
    ok = cur.rowcount > 0
    con.commit()
    con.close()
    return ok


def delete_kb_entry(entry_id: str) -> bool:
    """软删知识库条目。"""
    return _soft_delete_row("kb_entries", entry_id)


# ---------------------------------------------------------------------------
# SOP 管理
# ---------------------------------------------------------------------------

def create_sop(sop_id: str, name: str, description: str, content: str) -> str:
    con = _conn()
    con.execute(
        "INSERT INTO sops(id,name,description,content) VALUES(?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, description=excluded.description, "
        "content=excluded.content, deleted_at=NULL",  # 软删复活
        (sop_id, name, description, content))
    con.commit()
    con.close()
    return sop_id


def update_sop(sop_id: str, name: str, description: str, content: str) -> bool:
    con = _conn()
    cur = con.cursor()
    cur.execute("UPDATE sops SET name=?, description=?, content=? WHERE id=?",
                (name, description, content, sop_id))
    ok = cur.rowcount > 0
    con.commit()
    con.close()
    return ok


def get_sop(sop_id: str) -> dict | None:
    con = _conn()
    r = con.execute("SELECT id,name,description,content FROM sops WHERE id=? AND deleted_at IS NULL", (sop_id,)).fetchone()
    con.close()
    return dict(r) if r else None


def delete_sop(sop_id: str):
    """软删 SOP + 硬删员工关联。返回受影响员工。"""
    affected = _unlink("sop", sop_id)
    _soft_delete_row("sops", sop_id)
    return affected


# ---------------------------------------------------------------------------
# 连接器管理
# ---------------------------------------------------------------------------

def create_connector(conn_id: str, name: str, description: str, config: dict) -> str:
    con = _conn()
    con.execute(
        "INSERT INTO connectors(id,name,description,config) VALUES(?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, description=excluded.description, "
        "config=excluded.config, deleted_at=NULL",  # 软删复活
        (conn_id, name, description, json.dumps(config, ensure_ascii=False)))
    con.commit()
    con.close()
    return conn_id


def update_connector(conn_id: str, name: str, description: str, config: dict) -> bool:
    con = _conn()
    cur = con.cursor()
    cur.execute("UPDATE connectors SET name=?, description=?, config=? WHERE id=?",
                (name, description, json.dumps(config, ensure_ascii=False), conn_id))
    ok = cur.rowcount > 0
    con.commit()
    con.close()
    return ok


def get_connector(conn_id: str) -> dict | None:
    con = _conn()
    r = con.execute("SELECT id,name,description,config FROM connectors WHERE id=? AND deleted_at IS NULL", (conn_id,)).fetchone()
    if r:
        d = dict(r)
        d["config"] = json.loads(d["config"]) if d["config"] else {}
        con.close()
        return d
    con.close()
    return None


def delete_connector(conn_id: str):
    """软删连接器 + 硬删员工关联。返回受影响员工。"""
    affected = _unlink("connector", conn_id)
    _soft_delete_row("connectors", conn_id)
    return affected


# ---------------------------------------------------------------------------
# 写入（管理页调用）
# ---------------------------------------------------------------------------

def _build_interrupt_on(tool_ids: list[str]) -> dict:
    """根据所选工具的中断策略自动推导 interrupt_on（需审批的给 allowed_decisions）。"""
    con = _conn()
    cur = con.cursor()
    interrupt_on = {}
    for tid in tool_ids:
        row = cur.execute("SELECT needs_approval FROM tools WHERE id=?", (tid,)).fetchone()
        if row and row["needs_approval"]:
            interrupt_on[tid] = {"allowed_decisions": json.loads(row["needs_approval"])}
        else:
            interrupt_on[tid] = False
    con.close()
    return interrupt_on


def _set_links(cur, emp_id: str, data: dict):
    for table, key in (("employee_skills", "skills"), ("employee_tools", "tools"),
                       ("employee_kbs", "kbs"), ("employee_sops", "sops"),
                       ("employee_connectors", "connectors")):
        cur.execute(f"DELETE FROM {table} WHERE employee_id=?", (emp_id,))
        for v in data.get(key, []):
            cur.execute(f"INSERT OR IGNORE INTO {table} VALUES(?,?)", (emp_id, v))


def create_employee(data: dict) -> str:
    emp_id = data.get("id") or ("emp_" + time.strftime("%Y%m%d%H%M%S"))
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    interrupt_on = _build_interrupt_on(data.get("tools", []))
    con = _conn()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO employees(id,name,role,model,persona,backend,mcp_servers,interrupt_on,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, role=excluded.role, model=excluded.model, "
        "persona=excluded.persona, backend=excluded.backend, interrupt_on=excluded.interrupt_on, "
        "updated_at=excluded.updated_at, deleted_at=NULL",  # 软删复活：同 id 重建即复活
        (emp_id, data.get("name", emp_id), data.get("role", ""), data.get("model", ""),
         data.get("persona", ""), data.get("backend", "state"), "{}",
         json.dumps(interrupt_on, ensure_ascii=False), now, now))
    _set_links(cur, emp_id, data)
    con.commit()
    con.close()
    return emp_id


def update_employee(emp_id: str, data: dict) -> bool:
    con = _conn()
    cur = con.cursor()
    interrupt_on = _build_interrupt_on(data.get("tools", []))
    cur.execute(
        "UPDATE employees SET name=?,role=?,model=?,persona=?,backend=?,interrupt_on=?,updated_at=? WHERE id=?",
        (data.get("name", emp_id), data.get("role", ""), data.get("model", ""),
         data.get("persona", ""), data.get("backend", "state"),
         json.dumps(interrupt_on, ensure_ascii=False),
         time.strftime("%Y-%m-%d %H:%M:%S"), emp_id))
    if cur.rowcount == 0:
        con.close()
        return False
    _set_links(cur, emp_id, data)
    con.commit()
    con.close()
    return True


def delete_employee(emp_id: str):
    """软删员工 + 硬删其资源关联边（关联为配置关系，即时生效）。"""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    con = _conn()
    cur = con.cursor()
    cur.execute("UPDATE employees SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                (now, emp_id))
    for table in ("employee_skills", "employee_tools", "employee_kbs",
                  "employee_sops", "employee_connectors"):
        cur.execute(f"DELETE FROM {table} WHERE employee_id=?", (emp_id,))
    con.commit()
    con.close()
