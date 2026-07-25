# Deep Agents Backends 官方文档

> 来源：https://docs.langchain.com/oss/python/deepagents/backends.md
> 抓取时间：2026-07-25

## 概述

Deep Agents 通过工具（`ls`, `read_file`, `write_file`, `edit_file`, `delete`, `glob`, `grep`）向 agent 暴露文件系统。这些工具通过可插拔的后端架构运行。`read_file` 原生支持图片文件（.png, .jpg, .jpeg, .gif, .webp），以多模态内容块返回。

## StateBackend（默认）

```python
from deepagents.backends import StateBackend
# StateBackend() — 无参数
```

默认文件系统后端。文件存储在 LangGraph agent state 中，在当前线程内通过 checkpoint 持久化，但不跨线程共享。子代理写入的文件在子代理完成后保留在 state 中。

适合：草稿本、大工具输出的自动驱逐。

## FilesystemBackend（本地磁盘）

```python
from deepagents.backends import FilesystemBackend
FilesystemBackend(root_dir: str, virtual_mode: bool = False)
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `root_dir` | `str` | 可访问目录的绝对路径 |
| `virtual_mode` | `bool` | True 时沙箱化路径；阻止 `..`, `~`, 根外的绝对路径。**默认 False 即使设置了 root_dir 也不安全** |

安全警告：agent 可读取任何可访问文件（含密钥、凭据、.env）。与网络工具结合可能 SSRF 泄露。文件修改永久不可逆。建议：HITL 中间件、排除敏感路径、生产用沙箱后端、**始终 `virtual_mode=True`**。

## LocalShellBackend（本地 shell 执行）

```python
from deepagents.backends import LocalShellBackend
LocalShellBackend(
    root_dir: str,
    virtual_mode: bool = False,
    env: dict | None = None,
    inherit_env: bool = False,
    timeout: int = 120,
    max_output_bytes: int = 100000
)
```

扩展 `FilesystemBackend`，增加 `execute` 工具。通过 `subprocess.run(shell=True)` 执行，**无沙箱**。agent 可用你的用户权限执行任意 shell 命令。

## StoreBackend（LangGraph store — 跨线程持久化）

```python
from deepagents.backends import StoreBackend
StoreBackend(namespace: Callable[[Runtime], tuple[str, ...]] | None = None, store: BaseStore | None = None)
```

通过 LangGraph `BaseStore` 提供跨线程持久化文件存储。

**namespace 模式：**

```python
# 按用户隔离
StoreBackend(namespace=lambda rt: (rt.server_info.user.identity,))

# 按 assistant 共享
StoreBackend(namespace=lambda rt: (rt.server_info.assistant_id,))

# 按 thread 隔离
StoreBackend(namespace=lambda rt: (rt.execution_info.thread_id,))
```

Runtime 属性：`rt.context`（用户上下文）、`rt.server_info`（`assistant_id`, `graph_id`, `user.identity`）、`rt.execution_info`（`thread_id`, `run_id`, `checkpoint_id`）

## CompositeBackend（路由）

```python
from deepagents.backends import CompositeBackend
CompositeBackend(default: BackendProtocol, routes: dict[str, BackendProtocol] | None = None)
```

按路径前缀将文件操作路由到不同后端。`ls`, `glob`, `grep` 聚合所有后端的结果。较长的前缀优先。

```python
backend = CompositeBackend(
    default=StateBackend(),
    routes={
        "/memories/": StoreBackend(namespace=lambda _rt: ("memories",)),
    },
)
```

## ContextHubBackend

```python
from deepagents.backends import ContextHubBackend
ContextHubBackend(repo_id: str)  # owner/name 格式，需要 LANGSMITH_API_KEY
```

LangSmith Context Hub 仓库中的持久化文件存储。写编辑操作作为 Hub commits 提交。

## 后端方法协议

| 方法 | 签名 | 说明 |
|------|------|------|
| `ls` | `(path: str) -> LsResult` | 列出文件和目录 |
| `read` | `(file_path: str, offset=0, limit=2000) -> ReadResult` | 读文件内容 |
| `write` | `(file_path: str, content: str) -> WriteResult` | 创建文件（冲突返回 error） |
| `edit` | `(file_path, old_string, new_string, replace_all=False) -> EditResult` | 查找替换，`old_string` 必须唯一除非 `replace_all=True` |
| `glob` | `(pattern: str, path=None) -> GlobResult` | 文件名匹配 |
| `grep` | `(pattern: str, path=None, glob=None) -> GrepResult` | 文本搜索 |
| `delete` | `(file_path: str) -> DeleteResult` | 删除文件（可选，不支持时自动隐藏工具） |
| `execute` | 仅 SandboxBackendProtocol | 执行 shell 命令 |

返回类型总是结构化结果，带 `error` 字段。不要抛出异常。

## `create_file_data` 工具函数

```python
from deepagents.backends.utils import create_file_data
create_file_data(content: str) -> dict
```

用于格式化要写入 Store 的文件内容。返回包含 `content`, `encoding`, `created_at`, `modified_at` 的 dict。

## 权限

```python
FilesystemPermission(operations=["write"], paths=["/policies/**"], mode="deny")
```

`operations`: `"read"` | `"write"` 的列表；`paths`: glob 模式列表；`mode`: `"allow"` | `"deny"`。在调用后端之前评估。也可设为 `"interrupt"` 触发 HITL（deepagents>=0.6.8）。

## 迁移说明

- **0.5.0 起**：直接传后端实例，不要传工厂函数
- **0.7 起移除**：`BackendContext` 已移除。namespace 工厂现在直接接收 `Runtime`