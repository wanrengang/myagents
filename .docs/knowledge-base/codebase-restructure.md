---
name: codebase-restructure
description: 渐进式整理项目代码结构，拆分大文件、明确层边界、提取独立模块
metadata:
  type: project
status: pending
---

## 目标

不改变运行时逻辑，只做目录重组和文件拆分，降低后续维护成本。

## 方案

### 第一步：拆分 main.py（当前 1050 行）

| 新文件 | 内容 | 当前行数范围 |
|--------|------|------------|
| `app/routes/auth.py` | 登录、改密、me | 386-429 |
| `app/routes/chat.py` | 对话 SSE 流、会话 CRUD | 453-560 |
| `app/routes/admin/employees.py` | 员工管理路由 | 580-614 |
| `app/routes/admin/resources.py` | 技能/工具/知识库/SOP/连接器 CRUD | 622-831 |
| `app/routes/admin/users.py` | 用户管理路由 | 848-882 |
| `app/routes/me.py` | 我的分配、覆盖 | 943-1002 |
| `app/main.py` | 保留：生命周期、中间件、静态文件、路由挂载 | 精简后约 200 行 |

### 第二步：拆分 catalog.py（当前 976 行）

| 新文件 | 内容 |
|--------|------|
| `app/db/migrations.py` | 建表、字段迁移（soft_delete, must_change_password 等） |
| `app/db/seed.py` | 所有种子数据（FAQ、SOP、连接器、员工、管理员） |
| `app/models/employee.py` | 员工 CRUD |
| `app/models/skill.py` | 技能 CRUD |
| `app/models/kb.py` | 知识库+条目 CRUD |
| `app/models/sop.py` | SOP CRUD |
| `app/models/connector.py` | 连接器 CRUD |
| `app/models/user.py` | 用户 CRUD + 分配 |
| `app/catalog.py` | 保留：`get_employee_config`、`get_effective_config`、`catalog()` 等编译相关函数 |

### 第三步：提取公共层

| 新文件 | 内容 |
|--------|------|
| `app/db/__init__.py` | 统一数据库连接管理（代替各个模块独立的 `_conn()`） |
| `app/employee/__init__.py` | EmployeeSpec → build_spec → compile_agent 的编排逻辑（目前分散在 runtime + compiler） |

## 原则

- 不改变任何运行时行为
- 不修改 import 路径到「改了就跑不起来」的程度——重构完一个模块就验证一个
- 纯拆分，不改逻辑

## 不变的部分

- `app/tools/`、`app/workflows/`、`app/connectors/` 结构不动
- `app/compiler.py` 逻辑不动（但可以移到 `app/employee/compiler.py`）
- `app/runtime.py` 逻辑不动
- `app/traces.py`、`app/conversations.py`、`app/approvals.py`、`app/auth.py` 不动

## Why

- 当前找路由定义、找数据库操作、找业务逻辑要在 1050 行的 main.py 和 976 行的 catalog.py 里反复滚动搜索
- 多人协作时文件锁冲突概率高
- 单测只覆盖 catalog 等少数模块，因为大文件难以针对性 mock

## How to apply

按优先级排在其他功能开发之后。每次改一个拆分，改完跑 pytest 和手动验证基本对话流程。