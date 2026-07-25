# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 架构

**UniEmployee 数字员工平台** —— 基于 **deepagents 0.6.12** (LangGraph 1.2.9) 的多租户数字员工运行平台。

五层能力模型：`Employee → Workflow/SOP → Skill → Connector → Tool`

### 项目分层

```
app/                         # 后端（FastAPI）
├── main.py                  # 网关：SSE 流式对话 / 审批恢复 / 鉴权 / 管理 API / 前端静态挂载
├── compiler.py              # ★ 编译层：EmployeeSpec → create_deep_agent()
│   ├── ALL_LOCAL_TOOLS      # 全量本地工具注册表（dict）
│   ├── _assemble_tools()    # 按 spec 装配工具（本地+MCP+通用工具）
│   ├── build_backends()     # CompositeBackend（/memories/ + /skills/ StoreBackend 路由）
│   └── compile_agent()      # 主入口：播种技能→装配工具→拼 system_prompt→create_deep_agent
├── runtime.py               # agent 缓存、checkpointer、store、预热、失效
├── spec.py                  # EmployeeSpec Pydantic 模型 + load_spec(yaml)
├── catalog.py               # catalog.db（员工/技能/工具/知识库/SOP/连接器 CRUD + 用户管理）
├── auth.py                  # bcrypt + JWT + FastAPI 鉴权依赖
├── approvals.py             # HITL 审批单（内存版）
├── conversations.py         # 会话元数据 conversations.db
├── traces.py                # Trace 追踪 + TraceHandler(AsyncCallbackHandler)
├── errors.py                # 全局异常处理 → 干净 JSON 500
├── paths.py                 # 统一数据目录 DB 路径
├── employees/*.yaml         # 员工种子定义（仅首次启动写入 catalog.db）
├── tools/                   # Tool 实现
│   ├── kb.py                # kb_search(旧版), create_ticket
│   ├── data_tools.py        # get_my_id, run_python
│   ├── search.py            # bocha_search（联网搜索）
│   └── time_tools.py        # get_current_time
├── workflows/
│   └── refund.py            # 退款 StateGraph（内化审批：validate→calc→await_approval(interrupt)→execute）
└── connectors/
    └── crm_server.py        # CRM FastMCP stdio server（mock）

frontend/                    # Vue 3 + Vite + Naive UI + Pinia + Vue Router
├── src/views/               # login, chat, history, trace, admin, users, resources, home
├── src/api.js               # Axios 封装（自动注入 Bearer token）
├── src/router/index.js      # 路由：landing→login→app/{home,chat,history,admin,users,resources,trace}
├── src/stores/auth.js       # Pinia 认证状态
└── dist/                    # Vite 构建产物（FastAPI 挂载为静态文件）

skills/                      # 内置技能（SKILL.md + frontmatter）
├── product-faq/SKILL.md
├── complaint-handling/SKILL.md
├── data-analysis/SKILL.md
└── frontend-design/SKILL.md

skills-custom/               # 用户上传的自定义技能（gitignore）

tests/                       # pytest 测试
├── conftest.py              # tmp_db 夹具：临时 SQLite 库，不碰真实数据
└── test_*.py                # pytest -q 自动发现
```

### SQLite 数据库

| 文件 | 作用 |
|------|------|
| `catalog.db` | 员工/技能/工具/知识库/SOP/连接器/用户/分配 |
| `conversations.db` | 会话元数据（标题、预览、归属、计数、软删） |
| `demo.db` | LangGraph checkpointer（对话状态、消息历史） |
| `store.db` | 长期记忆（AsyncSqliteStore，按 user+员工隔离） |
| `traces.db` | 执行过程追踪（runs + events） |

### 核心数据流

```
用户消息 → POST /api/conversations/{id}/messages → SSE 流
  → runtime.get_agent(emp_id, user_id, overrides) → 按 key 缓存编译
  → agent.astream(input, config, stream_mode=["updates","messages"])
    → "messages" 模式: AIMessageChunk(token) → SSE type:token
    → "updates" 模式: 节点状态 → SSE type:thinking/tool/approval_required/todos/stage
  → traces.TraceHandler 捕获 LLM/工具回调 → traces.db（运行不阻塞）
  → __interrupt__ 到达 → approvals.create() → SSE type:approval_required
  → 审批人调用 POST /api/approvals/{id}/decision → Command(resume=...) 恢复
```

### 技能路由机制

1. 编译期 `compile_agent()` 把技能内容播种进 Store `namespace=(spec.id,)`
2. `_build_skill_routing()` 从 SKILL.md 提取触发条件 → 拼进 system_prompt 的"技能路由"节
3. `create_deep_agent(skills=["/skills/"])` 挂载 StoreBackend
4. 运行时模型通过 `read_file` 查阅完整规程，不能凭记忆跳过

### 记忆隔离

- CompositeBackend: 默认后端 + `/memories/` → StoreBackend `namespace=(user_id, emp_id)` + `/skills/` → StoreBackend `namespace=(spec.id,)`
- 记忆在编译期通过 `memory_namespace(user_id, emp_id)` 闭包捕获
- `ensure_user_memory()` 在首次对话时懒播种 AGENTS.md 模板

### 用户覆盖机制

- 模板配置（admin 设置）+ 每用户 add/remove 覆盖（通过 `user_employee_assignments` 表）
- 缓存键：admin → `emp_id`，普通用户 → `f"{emp_id}|{user_id}"`
- `get_effective_config()` 合并：`base ∪ add − remove`

### 审批双路径

- 轻量审批（create_ticket）：外层 agent 的 `interrupt_on` 拦截 → `allowed_decisions: [approve, reject]`
- 退款审批（Point2 内化）：refund StateGraph 内 `await_approval` 节点 `interrupt()` → 内层 thread `refund:{order_id}:{hash}` 隔离
  → decision 端点先 `resume_refund()` 恢复内层图 → 再用 `Command(resume=summary)` 恢复外层 agent

## 开发命令

```bash
# 运行服务
.venv/bin/uvicorn app.main:app --port 8787 --reload

# 前端开发
cd frontend && npx vite

# 前端构建
cd frontend && npx vite build

# 运行全部测试
.venv/bin/python -m pytest tests/ -v

# 运行单个测试文件
.venv/bin/python -m pytest tests/test_catalog.py -v

# 运行单个测试用例
.venv/bin/python -m pytest tests/test_catalog.py::test_name -v

# 安装依赖
.venv/bin/pip install -r requirements.txt

# Docker 部署
docker compose up -d --build

# 备份 5 个数据库
./scripts/backup.sh

# 为新员工创建 YAML 种子文件
# 在 app/employees/ 下新建 <id>.yaml，参考 xiaosu.yaml 或 xiaoshu.yaml
# 然后在 catalog.py seed_if_empty() 的 seeds dict 里注册

# 新建技能
# 创建 skills/<name>/SKILL.md（含 name/description frontmatter + 触发条件段落）
# 技能上传 API: POST /api/admin/skills/upload (multipart zip)
```

### 测试约定

- `tests/conftest.py` 的 `tmp_db` 夹具（autouse）自动把 catalog.db / conversations.db 替换为临时 SQLite 文件
- 测试不碰真实数据库文件
- 默认 `pytest -q`；慢测试（联网/浏览器）标记 `@pytest.mark.slow`

### 添加新员工

1. 创建 `app/employees/<id>.yaml`（人设、模型、技能列表、工具列表、MCP 配置、中断策略）
2. 在 `catalog.py seed_if_empty()` 的 `seeds` dict 里注册初始选中项（skills/tools/kbs/sops/cons）
3. 若有自定义工具，在 `compiler.py ALL_LOCAL_TOOLS` 注册
4. 若有新 MCP 连接器，在 `connectors/` 下创建 FastMCP stdio server
5. 若有新 workflow，在 `workflows/` 下创建 StateGraph
6. 重启服务 → 自动种子进 catalog.db，`runtime.warmup_all()` 预热编译

### 添加新工具

1. 在 `app/tools/` 下用 `@tool` 装饰器定义
2. 在 `app/compiler.py` 的 `ALL_LOCAL_TOOLS` dict 里注册
3. 员工在 catalog.db 的 `tools` 表里选择该工具（页面配置或种子数据）

### 添加新技能

1. 创建 `skills/<name>/SKILL.md`，含 frontmatter（name/description）+ `## 触发条件` 段落
2. 重启服务 → catalog.db 自动注册
3. 员工在管理后台勾选该技能

## 设计理念

- **深度模块**：compiler.py 是核心深度模块——表面是 `compile_agent()` 一个异步函数，内部做技能播种、工具装配、system_prompt 拼接、CompositeBackend 路由、MCP client 拉起
- **运行时以 catalog.db 为准**：employees/*.yaml 仅作种子源，页面化配置后运行时全从库读
- **Trace 不影响主流程**：所有写 traces.db 均吞异常
- **用户级记忆隔离**：compile_agent 编译期闭包捕获 user_id，避免运行时 get_config() 不可用问题
- **审批内化**：refund StateGraph 的 await_approval 节点用 interrupt() 原语挂起，不依赖外层 agent 的 interrupt_on 拦截