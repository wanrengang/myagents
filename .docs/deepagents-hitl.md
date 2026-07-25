# Deep Agents Human-in-the-loop 官方文档

> 来源：https://docs.langchain.com/oss/python/deepagents/human-in-the-loop.md
> 抓取时间：2026-07-25

## 概述

通过 LangGraph 的 interrupt 机制支持人工审批流程。`interrupt_on` 参数配置哪些工具需要人工批准。当设置后，`HumanInTheLoopMiddleware` 会自动加入默认中间件栈。

## 配置结构

`interrupt_on` 接受工具名到配置的映射：

- **`True`**：启用带默认选项的中断（approve, edit, reject, respond）
- **`False`**：对该工具禁用中断
- **`InterruptOnConfig`**：自定义配置，含 `allowed_decisions` + 可选 `when` 谓词

### 必需：Checkpointer

HITL 必须有 checkpointer（如 `MemorySaver`），通过 `checkpointer` 参数传递。

## 决策类型（allowed_decisions）

| 决策 | 行为 |
|------|------|
| `approve` | 用原参数执行工具 |
| `edit` | 修改工具参数后执行 |
| `reject` | 跳过执行，返回拒绝反馈给 agent |
| `respond` | 返回人类消息作为合成工具结果（用于"问用户"风格的工具） |

指导：用 `reject` 当人拒绝；用 `respond` 仅当人充当工具。副作用工具避免 `respond`。

## 条件中断

加 `when` 谓词到 `InterruptOnConfig`，只中断特定调用。谓词接收 `ToolCallRequest`，返回 True 中断 / False 自动批准。

## 处理中断

agent 暂停后返回控制。检查 `result.interrupts` — 包含 `action_requests` 和 `review_configs`。用 `Command(resume={"decisions": [...]})` 恢复。

注意：
1. 始终用 `version="v2"`（invoke 和 resume）
2. 用**相同**的 `config`（相同 `thread_id`）
3. 决策顺序要匹配 `action_requests` 顺序

### 编辑参数

```python
{"type": "edit", "edited_action": {"name": "tool_name", "args": {...}}}
```

### 拒绝消息

包含明确的 `message`。默认反馈告诉模型工具未执行、不要重试。

## 多个工具调用

批量中断：所有需要审批的工具调用批次合并在一次中断中。每个 `action_request` 提供一个决策。

## 子代理中断

每个子代理可有自己的 `interrupt_on` 配置，覆盖主 agent 设置。

## 文件系统权限中断（>=0.6.8）

```python
FilesystemPermission(operations=["write"], paths=["/policies/**"], mode="interrupt")
```

与 `interrupt_on` 合并，一个审批步骤同时覆盖自定义工具和受保护的文件系统路径。

## 最佳实践

- **始终用 checkpointer** — 状态持久化必需
- **同一 thread_id** 恢复
- **决策顺序匹配动作顺序**
- 高风险工具：完整控制（approve/edit/reject）
- 中风险：仅 approve/reject
- 低风险：禁用中断