# Deep Agents Python SDK 官方文档参考

> 来源：https://docs.langchain.com/oss/python/deepagents/overview.md
> 抓取时间：2026-07-25

## `create_deep_agent` 参数

| 参数 | 说明 |
|------|------|
| `model` | Provider-prefixed 模型字符串，如 `"anthropic:claude-sonnet-4-6"`, `"openai:gpt-5.5"`, `"google_genai:gemini-3.5-flash"`, `"ollama:north-mini-code-1.0"` |
| `tools` | 自定义函数、LangChain tools 或 MCP tools |
| `system_prompt` | 基础系统指令。也可以是 `SystemPromptConfig` dict: `{"prefix":..., "base":..., "suffix":...}` |
| `skills` | 技能目录路径数组，如 `["/skills/"]` |
| `memory` | AGENTS.md 文件路径数组，如 `["/memories/AGENTS.md"]` |
| `backend` | 文件系统后端（默认 StateBackend） |
| `permissions` | 路径级访问控制 |
| `subagents` | 自定义子代理 |
| `middleware` | 额外的中间件 |
| `interrupt_on` | 工具调用前暂停（HITL） |
| `response_format` | 结构化输出 schema |
| `state_schema` | 自定义图状态 schema |
| `context_schema` | 每次运行的运行时上下文 schema |
| `checkpointer` | 检查点（HITL 必需） |
| `store` | BaseStore 实例 |
| `debug` | 调试模式 |
| `name` | agent 名称 |
| `cache` | 缓存配置 |

返回值：`CompiledStateGraph[AgentState[ResponseT], ContextT, InputAgentState, OutputAgentState[ResponseT]]`

## system_prompt 覆盖

```python
create_deep_agent(..., system_prompt={"base": "..."})        # 覆盖 base
create_deep_agent(..., system_prompt={"base": None})          # 无 base
create_deep_agent(..., system_prompt={"prefix": "...", "suffix": "..."})  # 三明治
```

组装顺序：`prefix -> base -> suffix -> 任何模型特定 profile suffix`

## 默认中间件栈

1. `TodoListMiddleware` — todo 列表面板
2. `SkillsMiddleware` — 仅当传了 `skills`
3. `FilesystemMiddleware` — 文件系统操作 + 权限
4. `SubAgentMiddleware` — 子代理协调
5. `SummarizationMiddleware` — 消息历史压缩
6. `PatchToolCallsMiddleware` — 修复悬挂的工具调用
7. `AsyncSubAgentMiddleware` — 仅当异步子代理配置
8. **你的 middleware 参数** — 与默认同名的替换，否则追加到最后
9. Harness profile extras
10. 排除工具过滤
11. Prompt caching（Anthropic / Bedrock）
12. `MemoryMiddleware` — 仅当传了 `memory`，放在缓存之后
13. `HumanInTheLoopMiddleware` — 仅当设置了 `interrupt_on`

## MCP 工具

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

async with MultiServerMCPClient({
    "my_server": {"transport": "http", "url": "http://localhost:8000/mcp"}
}) as client:
    tools = await client.get_tools()
    agent = create_deep_agent(model="...", tools=tools)
```

## 子代理

```python
research_subagent = {
    "name": "research-agent",
    "description": "深入研究复杂问题",
    "system_prompt": "你是一个优秀的研究员",
    "tools": [internet_search],
    "model": "openai:gpt-5.5",
}
agent = create_deep_agent(model="google_genai:gemini-3.5-flash", subagents=[research_subagent])
```

## 注意

- 英文文档可能会在后续更新中变化，具体 API 以实际安装的 `deepagents` 版本为准

## 相关页面

- 后端：`/oss/python/deepagents/backends.md`
- 内存配置：`/oss/python/deepagents/customization.md`
- 技能：`/oss/python/deepagents/skills.md`
- 子代理：`/oss/python/deepagents/subagents.md`
- HITL：`/oss/python/deepagents/human-in-the-loop.md`
- 事件流：`/oss/python/deepagents/event-streaming.md`
- 沙箱：`/oss/python/deepagents/sandboxes.md`
- 权限：`/oss/python/deepagents/permissions.md`
- Profiles：`/oss/python/deepagents/profiles.md`