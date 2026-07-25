# Deep Agents Profiles 官方文档

> 来源：https://docs.langchain.com/oss/python/deepagents/profiles.md
> 抓取时间：2026-07-25

## HarnessProfile

`HarnessProfile` 打包配置，由 `create_deep_agent` 在建好聊天模型后应用。控制提示词组装、工具可见性、中间件和默认子代理设置。

## 注册键

- **Provider 级**：裸 provider 名（如 `"openai"`），适用于该 provider 的所有模型
- **Model 级**：`"openai:gpt-5.5"` 格式，仅特定模型

两者都存在时合并：model 级覆盖 provider 级，未设置则继承。

重新注册已有键会合并，不是替换。

## 配置字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `base_system_prompt` | `string` | 替换内置 agent system prompt（base key） |
| `system_prompt_suffix` | `string` | 附加在调用者的 suffix 之后 |
| `tool_description_overrides` | `Mapping[str, str]` | 按工具名覆盖描述 |
| `excluded_tools` | `frozenset[str]` | 按名称移除工具 |
| `excluded_middleware` | `frozenset[type[AgentMiddleware] \| str]` | 从默认栈中移除中间件 |
| `extra_middleware` | `Sequence[AgentMiddleware] \| Callable` | 追加到每个中间件栈 |
| `general_purpose_subagent` | `GeneralPurposeSubagentProfile` | 禁用、重命名或重提示通用子代理 |

### 中间件排除规则

`FilesystemMiddleware`, `SubAgentMiddleware`, 内部权限中间件**不能**被 `excluded_middleware` 移除（抛出 ValueError）。想隐藏工具用 `excluded_tools`。

## 提示组装规则

- `system_prompt=` 调用者提供的始终在**最前面**
- `system_prompt_suffix` 始终在**最后面**
- 每个子代理独立重新运行 profile 解析

## GeneralPurposeSubagentProfile

要运行无子代理/无 `task` 工具：

```python
general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)
```

`SubAgentMiddleware`（和 `task` 工具）仅在至少一个同步子代理存在时附加。

## ProviderProfile

声明模型构造方式（仅当传 `provider:model` 字符串时生效）。

| 字段 | 说明 |
|------|------|
| `init_kwargs` | 静态初始化参数，转发给 `init_chat_model` |
| `pre_init` | 构造前的副作用（如凭据检查） |
| `init_kwargs_factory` | 从运行时派生的 kwargs |

## 合并语义

| 字段 | 合并行为 |
|------|---------|
| `base_system_prompt`, `system_prompt_suffix` | 新值覆盖 |
| `tool_description_overrides` | 按 key 合并 |
| `excluded_tools`, `excluded_middleware` | Set 并集 |
| `extra_middleware` | 按 name 合并——新实例替换同名的 |
| `general_purpose_subagent` | 按字段合并（未设置字段继承） |