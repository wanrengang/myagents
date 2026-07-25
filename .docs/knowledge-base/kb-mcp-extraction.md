---
name: kb-mcp-extraction
description: 将知识库检索从内置闭包改为外挂 MCP 连接器，实现知识库内容与主系统解耦
metadata:
  type: project
status: pending
---

## 目标

把 `make_kb_search` 的关键词匹配逻辑从 `app/compiler.py` 闭包中抽出来，做成一个独立的 MCP server（FastMCP），员工通过勾选连接器来启用知识库检索。

## 设计

```
当前：
  catalog.db (kb_entries) → make_kb_search 闭包 → 模型调用

改为：
  独立 MCP server（FastMCP）
    └─ kb_search(query) 工具
        ├─ 支持向量检索（可选降级为关键词）
        └─ 从 catalog.db 或独立引擎读取
           │
           ▼
  MultiServerMCPClient 发现工具 → 模型调用
```

## 改动影响

- `app/compiler.py`：去掉 `make_kb_search`、`_assemble_tools` 中的 `kb_search` 分支
- `app/connectors/`：新建 `kb_server.py`（FastMCP）
- `catalog.py`：`_config_from_ids` 中知识库条目加载逻辑可能简化或保留
- 管理后台：员工配置时，需要勾选"知识库 MCP 连接器"来启用知识库检索
- 种子数据：`catalog.py seed_if_empty()` 自动注册 `kb-mcp` 连接器

## 关联

- 知识库条目管理仍保留在管理后台（资源中心 → 知识库）
- MCP server 直接从 `catalog.db` 读取条目，或后期替换为独立向量库

**Why:** 解耦知识库引擎，升级为向量检索时不改主系统代码；知识库内容变更即时生效，无需 invalidate 重编译。

**How to apply:** 等完整架构讨论结束后，按优先级别表逐步实施（参见 To-Do 清单 #33 知识库全文向量检索）。