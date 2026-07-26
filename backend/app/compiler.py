"""编译层：EmployeeSpec → create_deep_agent 实例。

整个 demo 最关键的设计——员工的一切产品化配置（人设、技能、工具、
连接器、审批策略）最终收敛为一次 create_deep_agent 调用。
技能与记忆通过 Store 的虚拟路径挂载（/skills/、/memories/），
技能内容在启动时从本地目录播种进 Store。

多员工：本文件是纯函数（spec 进、agent 出），新增员工只需加一个
employees/*.yaml，编译层零改动。所有工具集中登记在 ALL_LOCAL_TOOLS。
"""
import re
import sys
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend, LocalShellBackend
from deepagents.backends.utils import create_file_data
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.spec import EmployeeSpec
from app.tools.kb import create_ticket
from app.tools.data_tools import get_my_id, run_python
from app.tools.search import bocha_search
from app.tools.time_tools import get_current_time
from app.tools.wiki_tools import query_product_wiki, list_product_catalog
from app.workflows.refund import make_start_refund

ROOT = Path(__file__).resolve().parent.parent
VENV_BIN = str(ROOT / ".venv" / "bin")
# 全量本地工具注册表：每个员工按名挑选，编译层零改动即可扩展。
# 注意：分析师"小数"用 local_shell 后端，直接拿到 execute/read_file/ls/write_file
# 原生工具（参考官方 data-analysis 文档），不再需要 run_python 这类自定义子进程工具。
# kb_search 是"按员工所选知识库"的闭包工具，不在此注册（见 make_kb_search）。
# run_python：在数据目录直接跑 pandas/matplotlib，绕开 execute 在 virtual_mode 下
# /data/ 路径不映射的坑（模型用 pd.read_csv("/data/x.csv") 会失败）。
ALL_LOCAL_TOOLS = {
    "create_ticket": create_ticket,
    "run_python": run_python,
    "bocha_search": bocha_search,
    "get_my_id": get_my_id,
    "get_current_time": get_current_time,
    "query_product_wiki": query_product_wiki,
    "list_product_catalog": list_product_catalog,
}
# start_refund 不在此表：它需要运行时 checkpointer 注入（支持 Point2 内层图
# interrupt），由 _assemble_tools 用 make_start_refund(checkpointer) 工厂装配。

# 所有数字员工默认具备的通用工具（不依赖其 tools 字段声明）。
# 编译期无条件注入，解决「对话时不知道当前时间」的普遍问题。
GLOBAL_TOOL_NAMES = ["get_current_time"]


def make_kb_search(entries: list[dict]):
    """按某员工选中的知识库条目，生成一个专属的 kb_search 工具（闭包）。
    不同员工挂载不同知识库 → 检索范围不同。"""
    @tool
    def kb_search(query: str) -> str:
        """检索产品知识库。输入产品名/主题关键词，返回匹配的条目（含条目号，回答时需标注依据）。"""
        q = query.lower()
        hits = []
        for item in entries:
            score = sum(1 for k in item.get("keywords", []) if k in q)
            if score:
                hits.append((score, item))
        hits.sort(key=lambda x: -x[0])
        if not hits:
            return "未检索到相关条目。请换关键词重试；若仍无结果，告知用户需要核实并建议转人工。"
        return "\n\n".join(
            f"[{it['id']}] {it['title']}\n{it['content']}" for _, it in hits[:3])
    return kb_search


def _extract_skill_triggers(skill_md: str) -> str:
    """从 SKILL.md 提取触发条件文本。

    优先级：
      1. 正文 `## 触发条件` 或 `## 适用范围` 段落（语义最精确）；
      2. 兜底 frontmatter `description`（所有 SKILL.md 都有，含"当…时"触发语义）。
    """
    m = re.search(r"^##\s+(?:触发条件|适用范围)\s*\n(.+?)(?=^##\s|\Z)",
                  skill_md, re.MULTILINE | re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r"^description:\s*(.+)$", skill_md, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return ""


def _build_skill_routing(skills: list[dict]) -> str:
    """生成确定性技能路由指令，拼进 system_prompt。

    让模型在 system_prompt 里就看到「什么情况调什么技能」，而不是靠
    skills=["/skills/"] 挂载后模型自觉 read_file——后者无程序化保证，
    模型可能跳过。本函数把触发条件展开成明确指令，满足条件必须先查阅规程。
    """
    if not skills:
        return ""
    lines = [
        "",
        "## 技能路由（确定性激活）",
        "以下是你已挂载的技能。当用户消息满足某技能的触发条件时，",
        "必须先 read_file 查阅完整规程再执行，不可凭记忆跳过：",
        "",
    ]
    for s in skills:
        lines.append(f"### {s['name']}")
        lines.append(f"触发条件：{s.get('triggers') or s.get('description', '（未指定）')}")
        lines.append(f"规程路径：/skills/{s['name']}/SKILL.md")
        lines.append("")
    return "\n".join(lines)


async def _assemble_tools(spec: EmployeeSpec, checkpointer=None) -> tuple[list, object]:
    """按员工配置装配工具列表，返回 (tools, mcp_client)。

    组成：
      1. 本地注册表按名挑选（spec.tools 中声明的）；
      2. kb_search 闭包（按本员工选中的知识库条目生成）；
      3. start_refund 工厂注入（需运行时 checkpointer，支持 Point2 内层图 interrupt）；
      4. **通用工具**：GLOBAL_TOOL_NAMES 对所有员工无条件注入
         （即使 spec.tools=[] 也自动具备，去重避免重复）——
         目前含 get_current_time，让所有员工都能回答时间类问题；
      5. MCP 连接器工具（spec.mcp_servers 非空时拉起 stdio/sse 客户端）。
    """
    tools = []
    for name in spec.tools:
        if name == "kb_search":
            # 按本员工选中的知识库条目生成专属检索工具
            if spec.kb_entries:
                tools.append(make_kb_search(spec.kb_entries))
        elif name == "start_refund":
            # 退款工具需注入运行时 checkpointer（支持后续 Point2 内层图 interrupt）
            tools.append(make_start_refund(checkpointer))
        elif name in ALL_LOCAL_TOOLS:
            tools.append(ALL_LOCAL_TOOLS[name])

    # --- 通用工具：即使员工 tools=[] 也自动具备（去重避免重复）---
    have = {t.name for t in tools}
    for g in GLOBAL_TOOL_NAMES:
        if g in ALL_LOCAL_TOOLS and g not in have:
            tools.append(ALL_LOCAL_TOOLS[g])

    # --- MCP 连接器工具 ---
    mcp_client = None
    if spec.mcp_servers:
        servers = {}
        for name, cfg in spec.mcp_servers.items():
            cfg = dict(cfg)
            if cfg.get("transport") == "stdio":
                cfg["command"] = sys.executable
                cfg["args"] = [str(ROOT / a) for a in cfg.get("args", [])]
            servers[name] = cfg
        mcp_client = MultiServerMCPClient(servers)
        tools += await mcp_client.get_tools()
    return tools, mcp_client

def _init_model(model: str):
    """openai: 前缀模型在 deepagents 中默认走 Responses API，
    国内 MaaS 兼容端点只支持 /chat/completions，必须显式关掉，
    否则报 404。"""
    if model.startswith("openai:"):
        return init_chat_model(model, use_responses_api=False)
    return model

def memory_namespace(user_id: str | None, emp_id: str) -> tuple[str, ...]:
    """记忆 Store 命名空间：(user_id, emp_id)。

    必须在**编译期**就由 get_agent 把 user_id 闭包捕获进来——因为
    get_agent 本就按 (emp_id, user_id) 缓存 agent，编译期 user_id 已知。

    绝不能像早期实现那样在运行时调 get_config()["configurable"]["user_id"]：
    abefore_agent（加载记忆）阶段 langgraph 的 config 上下文尚未就绪，
    get_config() 取不到 → 回退 "default" → 读不到该用户的记忆
    （但工具调用「写记忆」时 get_config() 可取 → 能写入，造成「写进、读不出」）。
    技能路由用同款闭包写法（lambda rt: (spec.id,)）一直正常，即此理。
    """
    return (user_id or "default", emp_id)


def build_backends(spec: EmployeeSpec, store, user_id: str | None = None):
    """构造 CompositeBackend：默认后端 + /skills、/memories 路由。"""
    if spec.backend == "local_shell":
        default_backend = LocalShellBackend(
            root_dir=str(ROOT),
            virtual_mode=True,
            env={"PATH": f"{VENV_BIN}:/usr/bin:/bin"},
            inherit_env=True,
        )
    else:
        default_backend = StateBackend()
    return CompositeBackend(
        default=default_backend,
        routes={
            "/memories/": StoreBackend(namespace=lambda rt: memory_namespace(user_id, spec.id)),
            "/skills/": StoreBackend(namespace=lambda rt: (spec.id,)),
        },
    )


async def compile_agent(spec: EmployeeSpec, checkpointer, store, user_id: str | None = None):
    """返回 (agent, stage_meta, mcp_client)。
    mcp_client 由调用方按员工缓存保活；本函数不再持有模块级全局。
    user_id 由调用方（get_agent）传入并在编译期闭包进记忆命名空间。"""
    namespace = (spec.id,)

    # --- 播种技能到 Store（注意：key 不带路由前缀，
    #     CompositeBackend 会把 /skills/xxx 解析为 key /xxx）---
    skill_summaries = []
    for skill_name in spec.skills:
        # 目录可来自项目内 skills/，也可为外部绝对路径（如 ~/.agents/skills/...）
        sdir = spec.skill_dirs.get(skill_name) or f"skills/{skill_name}"
        skill_dir = Path(sdir) if Path(sdir).is_absolute() else ROOT / sdir
        skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        await store.aput(namespace, f"/{skill_name}/SKILL.md", create_file_data(skill_md))
        desc = next((l.split(":", 1)[1].strip() for l in skill_md.splitlines()
                     if l.startswith("description:")), "")
        triggers = _extract_skill_triggers(skill_md)
        skill_summaries.append({"name": skill_name, "description": desc, "triggers": triggers})

    # --- 记忆文件不在编译期播种：改为运行时按 (user_id, emp_id) 懒初始化
    #     （见 runtime.ensure_user_memory），实现用户级记忆隔离 ---

    # --- 工具：本地注册表按名挑选 + 知识库闭包 + 通用工具 + MCP 连接器 ---
    tools, mcp_client = await _assemble_tools(spec, checkpointer)
    tool_names = [t.name for t in tools]

    system_prompt = spec.persona + (("\n" + spec.sop_text) if spec.sop_text else "")
    system_prompt += _build_skill_routing(skill_summaries)
    sop_detail = spec.sop_text.strip() if spec.sop_text else "（无刚性 SOP，按技能规程执行）"

    backend = build_backends(spec, store, user_id)

    agent = create_deep_agent(
        model=_init_model(spec.model),
        tools=tools,
        system_prompt=system_prompt,
        skills=["/skills/"],
        memory=["/memories/AGENTS.md"],
        backend=backend,
        interrupt_on=spec.interrupt_on,
        checkpointer=checkpointer,
        store=store,
    )

    stage_meta = [
        {"stage": "employee", "status": "done",
         "detail_text": f"{spec.name}（{spec.role}）· {spec.model} · 工具 {len(tool_names)} 个"},
        {"stage": "sop", "status": "done", "detail_text": sop_detail},
        {"stage": "skills", "status": "done",
         "detail_text": "\n".join(f"· {s['name']}" for s in skill_summaries) or "（无）"},
    ]
    return agent, stage_meta, mcp_client
