# 数字员工平台模块业务逻辑

记录各模块的加载链路、执行方式和关键设计决策，方便后续开发和排查。

## 配置项全链路

### 数据流向总图

```
管理后台勾选配置
       │
       ▼
catalog.db 关联表（employee_skills / employee_tools / employee_kbs / employee_sops / employee_connectors）
       │
       ▼
get_employee_config() → _config_from_ids()
       │   从关联表查出员工勾选的资源 id → 拼出完整配置 dict
       ▼
build_spec() → EmployeeSpec
       │
       ▼
compile_agent() → create_deep_agent()
```

### 修改配置后的生效流程

```
管理后台保存配置
  → catalog.update_employee() 写库
  → runtime.invalidate(emp_id) 清进程内存缓存
  → 下次用户发消息，get_agent() 缓存未命中
  → 重新 compile_agent() → 从 DB 读新配置 → 重建 agent
```

不需要重启服务，但需要等下一次对话触发重编译。首次触发时有短暂延迟（模型初始化 + MCP 子进程拉起）。

### 缓存机制

```python
_agents = {}    # 进程内存 dict，key="emp_id" 或 "emp_id|user_id"
_mcp_clients = {}  # 进程内存 dict，MCP 连接器实例
```

- 编译好的 agent 只存在当前进程内存里
- 重启服务 → 全部清空 → `warmup_all()` 逐个预热
- 多进程/多实例部署 → 各进程独立缓存，不共享

---

## 技能 Skills

### 加载链路

```
管理后台勾选技能
  → employee_skills 表写入
  → _config_from_ids() 查出技能 id 列表 → spec.skills
  → compile_agent() 遍历 spec.skills：
      1. 从磁盘 skills/<name>/SKILL.md 读全文
      2. await store.aput((spec.id,), "/<name>/SKILL.md", data) 播种到 Store
      3. 提取 frontmatter description + 触发条件 → 拼成路由摘要
  → 路由摘要拼入 system_prompt
  → create_deep_agent(skills=["/skills/"])
```

### 执行方式（双重机制）

| 机制 | 内容 | 时机 |
|------|------|------|
| **system_prompt 路由指令** | 技能名 + 触发条件 + 文件路径（每个技能 2-3 行） | 每轮对话 |
| **StoreBackend 按需读取** | `/skills/` → StoreBackend `namespace=(spec.id,)` | 模型调用 read_file 时 |

第一层让模型"知道有什么技能可用"，第二层让模型通过 `read_file` 按需加载完整规程。

### 路由摘要示例

拼进 system_prompt 的内容（每个技能约 3 行）：

```
## 技能路由（确定性激活）
当用户消息满足某技能的触发条件时，必须先 read_file 查阅完整规程再执行：

### product-faq
触发条件：产品知识问答技能。当用户咨询产品参数、价格、保修时使用。
规程路径：/skills/product-faq/SKILL.md
```

### 关键设计点

- **不是全量加载**：system_prompt 只含路由摘要，完整规程在模型判定命中后按需 read_file
- **上传 vs 内置**：没有区别。上传技能放在 `skills-custom/<id>/`，dir 字段指向对应目录
- **用户隔离**：❌ 不隔离。所有用户共享 `namespace=(spec.id,)`

### SKILL.md 结构要求

```yaml
---
name: product-faq
description: 产品知识问答技能。当用户咨询产品参数、价格时使用。
---
# 技能名称

## 触发条件（或 ## 适用范围）
描述什么情况下触发此技能。

## 执行步骤
1. 调 kb_search 检索知识库
2. 仅依据检索结果回答
...
```

---

## 工具 Tools

### 加载链路

```
管理后台勾选工具
  → employee_tools 表写入
  → _config_from_ids() 查出工具 id 列表 → spec.tools
  → _assemble_tools() 装配：
```

### 工具装配规则

| 来源 | 条件 | 说明 |
|------|------|------|
| **ALL_LOCAL_TOOLS** | `name in ALL_LOCAL_TOOLS` | 注册表 dict 按名查询 |
| **kb_search** | `name == "kb_search"` | 闭包生成，捕获知识库条目 |
| **start_refund** | `name == "start_refund"` | 工厂注入运行时 checkpointer |
| **MCP 连接器** | spec.mcp_servers 非空 | MultiServerMCPClient 动态发现 |
| **get_current_time** | 无条件注入（GLOBAL_TOOL_NAMES） | 所有员工自动具备 |

### 本地工具注册表

```python
ALL_LOCAL_TOOLS = {
    "create_ticket": create_ticket,  # 工单登记
    "run_python": run_python,        # 运行 Python 代码
    "bocha_search": bocha_search,    # 联网搜索
    "get_my_id": get_my_id,          # 获取当前用户 ID
    "get_current_time": get_current_time,  # 获取当前时间
}
# start_refund 不在此表，通过工厂注入
```

### 中断审批

`interrupt_on` 根据工具的 `needs_approval` 字段自动推导：

```python
# catalog.py _build_interrupt_on()
for tid in tool_ids:
    row = SELECT needs_approval FROM tools WHERE id=tid
    interrupt_on[tid] = {allowed_decisions} or False
```

Point2 内化审批：refund StateGraph 的 `await_approval` 节点使用 `interrupt()` 原语，不再依赖外层 agent 的 `interrupt_on`。

---

## 知识库 Knowledge Bases

### 加载链路

```
管理后台勾选知识库
  → employee_kbs 表写入
  → _config_from_ids() 查出知识库 id 列表
  → 遍历每个选中的知识库，查出所有条目：
    for kb in kbs:
        for e in kb_entries where kb_id=kb:
            entries.append({id, title, keywords, content})
  → entries 传入 make_kb_search(entries) 生成闭包工具
```

### 执行方式

```
模型调用 kb_search(查询词)
  → 遍历所有条目的 keywords 字段做关键词匹配
  → score = sum(1 for k in keywords if k in query)
  → 按得分降序，返回前 3 条
```

### 关键设计点

- **知识库不是独立模块**，没有挂载文件系统
- 通过 `kb_search` 工具对外暴露，工具在编译期由 `make_kb_search(entries)` 闭包生成
- **搜索是关键词匹配**，不是向量检索。条目 `keywords` 字段决定匹配精度
- **全量加载到闭包**：所有条目在编译期读入内存，后续条目增多会膨胀
- **必须有对应技能配合**才能触发查询（product-faq → 调用 kb_search）

---

## SOP 流程文档

### 加载链路

```
管理后台勾选 SOP
  → employee_sops 表写入
  → _config_from_ids() 查出 SOP id 列表
  → 遍历每个选中的 SOP，拼 content：
    for sid in sops:
        sop_text += sops[sid].content + "\n\n"
  → sop_text 拼入 system_prompt（compile_agent 第 227 行）
```

### 执行方式

- SOP 全文直接写在 system_prompt 中，模型每轮对话都能看到
- 不需要调用工具或 read_file
- 多个 SOP 按顺序拼接

### 关键设计点

- **全量加载到 system_prompt**：SOP 内容多时会直接增加每次对话的 token 消耗
- 当前两个 SOP 约 900 字符，影响较小
- SOP 是"硬性流程"，技能是"软性规程"——SOP 直接可见，技能需 read_file

---

## 连接器 Connectors (MCP)

### 加载链路

```
管理后台配置连接器
  → connectors 表写入（config 字段存 transport/command/args）
  → employee_connectors 表写入
  → _config_from_ids() 查出连接器 id 列表
  → 解析 config JSON → mcp_servers[cid] = config
  → _assemble_tools():
    mcp_client = MultiServerMCPClient(servers)
    tools += await mcp_client.get_tools()
```

### 执行方式

- 编译期拉起 MCP stdio 子进程（如 CRM 连接器的 `crm_server.py`）
- 通过 `MultiServerMCPClient` 发现 MCP server 暴露的工具
- 发现的工具和本地工具合并，一起传给 LLM
- MCP 子进程在 agent 缓存期间一直存活

### 连接器配置格式

```json
{
  "transport": "stdio",
  "command": "/usr/bin/python3",
  "args": ["app/connectors/crm_server.py"]
}
```

### 关键设计点

- **服务关闭时子进程未清理**：当前没有在 lifespan 的 shutdown 中关闭 MCP 客户端
- MCP 子进程由 `_mcp_clients` 保活，invalidate 时会关闭

---

## 知识库、技能、工具的依赖关系

```
         用户问题
            │
            ▼
    技能路由（system_prompt）
    ┌─────────────────┐
    │ product-faq     │   命中触发条件
    │ complaint       │   → 调 read_file 读 SKILL.md
    │ data-analysis   │   → 按步骤执行
    └─────────────────┘
            │
            ▼
    SKILL.md 指令
    ┌─────────────────┐
    │ 第2步：调       │   ← 技能告诉模型"调 kb_search"
    │ kb_search       │
    │ 检索知识库      │
    └─────────────────┘
            │
            ▼
    kb_search 工具              ← 工具必须勾选才有
    ┌─────────────────┐
    │ 遍历知识库条目  │         ← 知识库条目必须勾选才在闭包里
    │ 关键词匹配      │
    │ 返回前3条       │
    └─────────────────┘
```

三者缺一不可：
- 有知识库无技能 → 模型不知道何时去查
- 有知识库有技能无工具 → 技能说"查知识库"但模型没有 kb_search 可用
- 有技能无知识库 → kb_search 查到为空

---

## 数据库结构

| 数据库 | 位置 | 作用 | 读写方 | 生命周期 |
|--------|------|------|--------|---------|
| catalog.db | DB_FILES | 员工配置、技能/工具/知识库/SOP/连接器/用户/分配 | 管理后台 CRUD | 长期保留 |
| conversations.db | DB_FILES | 会话元数据（标题/预览/归属/消息数） | 对话列表查询 | 随对话 |
| demo.db | DB_FILES | LangGraph checkpointer（对话状态/消息历史） | agent 运行时 | 随对话 |
| store.db | DB_FILES | 长期记忆 + 技能文件内容（StoreBackend） | agent 运行时 | 随对话 |
| traces.db | DB_FILES | 执行过程追踪（run/event） | TraceHandler 回调 | 可清理 |

分开是为了避免 SQLite 单写者锁竞争，以及不同数据的备份/清理策略不同。