"""运行时：多员工 agent 缓存 + checkpointer + store。

- 每个员工独立编译、独立缓存（_agents[emp_id]），各自的 MCP stdio
  会话由各自的 mcp_client 保活（_mcp_clients[emp_id]）。
- thread_id = conversation_id，会话状态全在 AsyncSqliteSaver（demo.db），
  人工审批可跨请求 resume。
- 长期记忆在 Store 的 /memories/ 路由，按 (user_id, emp_id) 命名空间隔离；
  Store 用 AsyncSqliteStore（store.db），记忆重启不丢（生产可换 Postgres）。
- 员工配置来自 catalog.db（页面可配置）；discover_employees / get_agent 改读目录库，
  employees/*.yaml 仅作种子来源。
"""
import asyncio
from pathlib import Path

from langgraph.store.sqlite import AsyncSqliteStore

from app import catalog
from app.spec import EmployeeSpec
from app.compiler import compile_agent

ROOT = Path(__file__).resolve().parent.parent

_store = None          # 生命周期启动时由 lifespan 注入 AsyncSqliteStore(store.db)
_checkpointer = None  # 生命周期启动时由 lifespan 注入 AsyncSqliteSaver(demo.db)
_agents = {}          # emp_id -> (agent, stage_meta)
_mcp_clients = {}     # emp_id -> mcp_client | None
_lock = asyncio.Lock()


def set_checkpointer(cp):
    global _checkpointer
    _checkpointer = cp


def set_store(store):
    global _store
    _store = store


def discover_employees() -> list[dict]:
    """返回精简元数据（含 skills/tools，供选择器与历史恢复匹配用），不编译。"""
    out = []
    for m in catalog.list_employees_meta():
        cfg = catalog.get_employee_config(m["id"]) or {}
        out.append({
            "id": m["id"],
            "name": m["name"],
            "role": m["role"],
            "model": m["model"],
            "skills": cfg.get("skills", []),
            "tools": cfg.get("tools", []),
        })
    return out


def discover_assigned_employees(user_id: str) -> list[dict]:
    """返回某用户已分配员工的精简元数据（对话选择器用，只含已分配）。"""
    out = []
    for eid in catalog.assigned_employee_ids(user_id):
        m = next((x for x in catalog.list_employees_meta() if x["id"] == eid), None)
        if not m:
            continue
        cfg = catalog.get_employee_config(eid) or {}
        out.append({
            "id": eid,
            "name": m["name"],
            "role": m["role"],
            "model": m["model"],
            "skills": cfg.get("skills", []),
            "tools": cfg.get("tools", []),
        })
    return out


def build_spec(cfg: dict) -> EmployeeSpec:
    """目录库配置 → EmployeeSpec（编译层输入）。"""
    return EmployeeSpec(
        id=cfg["id"], name=cfg["name"], role=cfg.get("role", ""), model=cfg["model"],
        persona=cfg["persona"], backend=cfg.get("backend", "state"),
        interrupt_on=cfg.get("interrupt_on", {}),
        skills=cfg.get("skills", []), tools=cfg.get("tools", []),
        mcp_servers=cfg.get("mcp_servers", {}),
        kbs=cfg.get("kbs", []), kb_entries=cfg.get("kb_entries", []),
        sop_text=cfg.get("sop_text", ""), connectors=cfg.get("connectors", []),
        skill_dirs=cfg.get("skill_dirs", {}),
    )


def invalidate(employee_id: str):
    """配置变更后丢弃缓存，下次 get_agent 重新编译。
    同时清掉该员工的全部按用户变体（emp_id|user_id）。"""
    _agents.pop(employee_id, None)
    _mcp_clients.pop(employee_id, None)
    for k in list(_agents.keys()):
        if k.startswith(f"{employee_id}|"):
            _agents.pop(k, None)
            _mcp_clients.pop(k, None)


async def dump_store(employee_id: str = "xiaosu") -> list[dict]:
    """调试用：导出 Store 里某员工的全部虚拟文件（记忆/技能的实体所在）。"""
    items = await _store.asearch((employee_id,))
    return [{"key": i.key, "value": i.value} for i in items]


async def dump_user_memory(user_id: str, employee_id: str) -> list[dict]:
    """调试用：导出某用户在某员工下的记忆（/memories namespace=(user_id, emp_id)）。"""
    items = await _store.asearch((user_id, employee_id))
    return [{"key": i.key, "value": i.value} for i in items]


async def ensure_user_memory(user_id: str, employee_id: str):
    """用户级记忆懒初始化：若 (user_id, emp_id) namespace 下还没有 AGENTS.md，
    播种一份空模板。记忆按用户隔离——不同用户问同一员工，记忆互不可见。
    同时建好看板目录 workspace/data/{user_id}/，供数据分析师按用户隔离生成看板。"""
    from deepagents.backends.utils import create_file_data
    ns = (user_id, employee_id)
    existing = [i.key for i in await _store.asearch(ns)]
    if "/AGENTS.md" not in existing:
        await _store.aput(ns, "/AGENTS.md",
                          create_file_data("## 用户档案\n（随着对话积累）\n"))
    # 用户专属看板目录
    (ROOT / "workspace" / "data" / user_id).mkdir(parents=True, exist_ok=True)


async def get_agent(employee_id: str, user_id: str | None = None,
                     overrides: dict | None = None):
    """按员工懒编译 + 进程内缓存。

    - 管理员 / 模板路径：user_id=None → 缓存键为 emp_id，用纯模板配置。
    - 普通用户路径：user_id 给定 → 缓存键为 f"{emp_id}|{user_id}"，
      用 get_effective_config（模板 + 该用户覆盖合并）编译，A/B 互不影响。
    overrides 由调用方传入（来自该用户的分配行），避免在编译层再查库。
    """
    async with _lock:
        if user_id:
            key = f"{employee_id}|{user_id}"
            cfg = catalog.get_effective_config(user_id, employee_id)
            if not cfg:  # 兜底：分配缺失时用纯模板
                cfg = catalog.get_employee_config(employee_id)
        else:
            key = employee_id
            cfg = catalog.get_employee_config(employee_id)
        if not cfg:
            raise KeyError(f"未知员工：{employee_id}")
        if key not in _agents:
            agent, stage_meta, mcp_client = await compile_agent(
                build_spec(cfg), _checkpointer, _store, user_id=user_id)
            _agents[key] = (agent, stage_meta)
            _mcp_clients[key] = mcp_client
    return _agents[key]


async def warmup_all():
    """生命周期启动时预热所有员工，切换即时可用。
    单个员工配置错误（如模型名写错）不应拖垮整个服务——记录后跳过。"""
    for emp in discover_employees():
        try:
            await get_agent(emp["id"])
        except Exception as e:
            print(f"[warmup] 跳过员工 {emp['id']}（编译失败）：{type(e).__name__}: {e}")
