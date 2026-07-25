# Deep Agents Event Streaming 官方文档

> 来源：https://docs.langchain.com/oss/python/deepagents/event-streaming.md
> 抓取时间：2026-07-25

## 概述

Deep Agents 在 LangGraph streaming 基础上增加了子代理投影。`stream.subagents` 为每个委托的 `task` 调用提供一个流句柄。

## 子代理流字段

每个子代理流暴露的投影：

| 字段 | 用途 |
|------|------|
| `name` | 子代理名称 |
| `messages` | 子代理发出的消息 |
| `subagents` | 嵌套的子代理调用 |
| `output` | 最终状态或完成信号 |
| `path` | 子代理流的命名空间路径 |
| `status` | 生命周期状态（started/completed/failed/interrupted） |
| `tool_calls` | 子代理的工具调用 |

## 子代理生命周期

```python
stream = agent.stream_events({...}, version="v3")
for subagent in stream.subagents:
    print(subagent.name, subagent.path, subagent.status)
    for message in subagent.messages:
        print(message.text)
```

## 消息流

- `stream.messages` — 协调器的消息
- `subagent.messages` — 子代理的消息

## 工具调用流

- `stream.tool_calls` — 协调器工具调用
- `subagent.tool_calls` — 子代理工具调用

每个工具调用提供：`tool_name`, `input`, `completed`, `error`, `output_deltas`

## 并发消费

- **异步（推荐）**：`astream_events` + `asyncio.gather` 并行处理协调器和子代理
- **同步**：`stream.interleave("messages", "subagents")` 产生 `(name, item)` 元组

## 子代理 vs 子图

- `stream.subgraphs` — 展示图执行结构
- `stream.subagents` — 展示产品级 Deep Agents 任务委派

推荐在 UI 中用 `stream.subagents`，因为它隐藏内部图节点，直接暴露子代理概念。