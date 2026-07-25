# Deep Agents Skills 官方文档

> 来源：https://docs.langchain.com/oss/python/deepagents/skills.md
> 抓取时间：2026-07-25

## 概述

技能将领域专业知识封装为可复用的目录。每个技能是一个目录，包含 `SKILL.md` 文件（YAML frontmatter + markdown 指令）。支持文件可以放在 `scripts/`, `references/`, `assets/` 下。

Agent 启动时仅加载 `name` 和 `description`，任务匹配时再读取完整 `SKILL.md`。

## Frontmatter 字段

| 字段 | 必需 | 说明 |
|------|------|------|
| `name` | 是 | 小写字母数字+连字符，1-64 字符，与父目录名一致 |
| `description` | 是 | 技能功能与使用时机，最多 1024 字符 |
| `license` | 否 | 许可证 |
| `compatibility` | 否 | 环境要求，最多 500 字符 |
| `metadata` | 否 | 任意键值对 |
| `allowed-tools` | 否 | 空格分隔的预批准工具列表（实验性） |

示例：
```yaml
---
name: langgraph-docs
description: Use this skill for requests related to LangGraph in order to fetch relevant documentation.
license: MIT
metadata:
  author: langchain
  version: "1.0"
---
```

## 渐进式披露（三级加载）

| 级别 | 加载内容 | 时机 |
|------|---------|------|
| 1. 元数据 | `name` + `description` | agent 启动时，对所有配置的技能 |
| 2. 指令 | 完整 `SKILL.md` 正文 | 技能被调用时 |
| 3. 资源 | 支持文件（scripts/references/assets） | 按需 |

SkillsMiddleware 负责级别 1 和 2，LLM 负责级别 3。

## 用法

1. 创建顶级 `skills/` 目录
2. 为每个技能建子目录
3. 添加 `SKILL.md`（frontmatter + markdown）
4. 通过 `skills` 参数传给 agent：`create_deep_agent(..., skills=["/skills/"])`
5. 调用 agent

## 支持资源目录

- **`scripts/`** — 可执行代码（API 客户端、数据转换、验证）
- **`references/`** — 补充文档（技术参考、领域指南）
- **`assets/`** — 静态资源（模板、图片、数据文件）

从 `SKILL.md` 引用时用相对路径。

## 后端和技能加载

- **StateBackend**: 通过 `invoke(files={...})` 用 `create_file_data()` 种子文件
- **StoreBackend**: 用 Store 持久化
- **FilesystemBackend**: 从磁盘读取

```python
# StateBackend 种子
from deepagents.backends.utils import create_file_data
await store.aput(namespace, "/skill_name/SKILL.md", create_file_data(skill_md))
```

## 动态技能列表（按角色/用户）

```python
SKILLS_BY_ROLE = {
    "engineering": ["/skills/code-review/", "/skills/testing/"],
    "data": ["/skills/sql-analysis/", "/skills/visualization/"],
}
```

## 子代理技能

- 通用子代理：自动继承主 agent 的 `skills`
- 自定义子代理：**不继承**，需单独加 `skills` 参数
- 技能状态完全隔离：主 agent 和子代理的技能互不可见

## 技能 vs 记忆 vs 工具

| | 技能 | 记忆 | 工具 |
|--|------|------|------|
| 用途 | 按需能力（渐进披露） | 启动时加载的持久上下文 | 程序化动作 |
| 加载 | agent 判定相关时读取 | agent 启动时加载 | 每轮都可用 |
| 格式 | 命名目录中的 SKILL.md | AGENTS.md 文件 | 绑定到 agent 的函数 |

## 约束

- SKILL.md 必须 < 10 MB
- 多个技能源同名时，`skills` 数组中**靠后的源优先**
- 路径必须用正斜杠
- name 必须小写字母数字+连字符，1-64 字符，匹配父目录名
- description 最多 1024 字符
- compatibility 最多 500 字符