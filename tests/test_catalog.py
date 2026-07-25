"""目录库（员工/技能/工具/知识库/SOP/连接器）CRUD 回归测试。"""
import json
import sqlite3

from app import catalog


def _seed_tool(tid: str, needs_approval=None):
    con = sqlite3.connect(str(catalog.DB))
    con.execute(
        "INSERT OR IGNORE INTO tools(id,name,description,source,needs_approval) VALUES(?,?,?,?,?)",
        (tid, tid, "d", "local", json.dumps(needs_approval) if needs_approval else None))
    con.commit()
    con.close()


# ---- 员工 ----

def test_employee_crud_and_interrupt_derivation():
    _seed_tool("start_refund", ["approve", "reject"])
    _seed_tool("kb_search")
    eid = catalog.create_employee({
        "name": "测试员", "model": "openai:m", "backend": "state", "persona": "p",
        "tools": ["start_refund", "kb_search"], "skills": [], "kbs": [], "sops": [], "connectors": [],
    })
    cfg = catalog.get_employee_config(eid)
    assert cfg["name"] == "测试员"
    assert set(cfg["tools"]) == {"start_refund", "kb_search"}
    # interrupt_on 由工具 needs_approval 自动推导
    assert cfg["interrupt_on"]["start_refund"]["allowed_decisions"] == ["approve", "reject"]
    assert cfg["interrupt_on"]["kb_search"] is False

    # 更新（改名 + 去掉工具）
    assert catalog.update_employee(eid, {
        "name": "改名", "model": "openai:m", "backend": "state", "persona": "p2",
        "tools": [], "skills": [], "kbs": [], "sops": [], "connectors": [],
    })
    cfg2 = catalog.get_employee_config(eid)
    assert cfg2["name"] == "改名"
    assert cfg2["tools"] == []

    # 删除
    catalog.delete_employee(eid)
    assert catalog.get_employee_config(eid) is None


# ---- 知识库 + 条目 ----

def test_kb_and_entries_crud():
    catalog.create_kb("kb1", "库1", "说明")
    catalog.create_kb_entry("kb1", "E1", "标题1", ["k1", "k2"], "内容1")
    entries = catalog.list_kb_entries("kb1")
    assert len(entries) == 1 and entries[0]["title"] == "标题1"
    assert entries[0]["keywords"] == ["k1", "k2"]

    assert catalog.update_kb_entry("E1", "标题改", ["k3"], "内容改")
    assert catalog.list_kb_entries("kb1")[0]["title"] == "标题改"

    catalog.delete_kb("kb1")
    assert catalog.list_kb_entries("kb1") == []


# ---- SOP ----

def test_sop_crud():
    catalog.create_sop("sop1", "SOP1", "d", "content")
    assert catalog.get_sop("sop1")["content"] == "content"
    assert catalog.update_sop("sop1", "SOP改", "d2", "c2")
    assert catalog.get_sop("sop1")["name"] == "SOP改"
    catalog.delete_sop("sop1")
    assert catalog.get_sop("sop1") is None


# ---- 连接器 ----

def test_connector_crud():
    catalog.create_connector("c1", "连接器1", "d", {"transport": "stdio"})
    c = catalog.get_connector("c1")
    assert c["config"]["transport"] == "stdio"
    assert catalog.update_connector("c1", "改", "d2", {"transport": "stdio", "command": "x"})
    assert catalog.get_connector("c1")["config"]["command"] == "x"
    catalog.delete_connector("c1")
    assert catalog.get_connector("c1") is None


# ---- 技能 upsert ----

def test_skill_upsert_and_delete():
    catalog.upsert_skill("sk1", "技能1", "d", "skills/sk1")
    assert catalog.get_skill("sk1")["dir"] == "skills/sk1"
    catalog.upsert_skill("sk1", "技能改", "d2", "skills-custom/sk1")  # 同 id 更新
    assert catalog.get_skill("sk1")["dir"] == "skills-custom/sk1"
    catalog.delete_skill("sk1")
    assert catalog.get_skill("sk1") is None
