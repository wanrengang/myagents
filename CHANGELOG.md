# Changelog

## 0.3.0 (2026-07-26)

### 重构
- 移动 5 个 SQLite 数据库从根目录到 `data/db/`，`paths.py` 默认路径同步更新
- 删除废弃的 `app/static/` HTML 文件（已被 `frontend/src/` Vue 前端替代）
- 所有 `.vue`/`.js` 文件顶部加中文文件说明，`__init__.py` 补充包说明

### 新增
- 前端可复用分页组件 `PaginationBar.vue`
- 知识库条目详情弹窗（查看完整内容）
- SOP 展开/收起全文
- 技能内容查看弹窗（SKILL.md 全文）
- 技能编辑弹窗新增 SKILL.md 内容字段
- 公共知识库条目只读接口 `GET /api/knowledge-bases/{id}/entries`
- `pyproject.toml` 项目元数据文件
- `CLAUDE.md`、`TODO.md` 项目文档

### 修复
- 前端路由跳转全部改为按 name 跳转，解决绝对路径不匹配子路由的问题
- 左侧菜单切换闪烁（移除 transition + 改用 keep-alive 缓存组件）
- ChatView 缺失 `useRouter` 导入导致"执行过程"按钮无反应
- HistoryView 缺失 `reactive` 导入导致页面空白
- 资源中心知识库条目 API 路径 `/admin/kbs/` → `/admin/knowledge-bases/`
- 资源中心普通用户无法查看知识库条目（后端新增公共 API）
- Trace 默认折叠（traceExpanded: true → false）
- "执行过程"链接从 `<a href="/trace">` 改为 `router.resolve`
- $router.push('/history') 改为 `{name:'history'}`

### 丰富
- FAQ 知识库从 6 条扩展到 30 条（5 产品线 + 通用政策）
- MOCK_ORDERS 从 3 个扩展到 10 个
- CRM 客户从 2 个扩展到 6 个
- 销售数据集从 2 产品 × 24 行扩展到 5 产品 × 60 行
- SOP 内容全部重写为完整版本
- product-faq / complaint-handling 技能文档扩充
- 小苏 / 小数人设扩充

### 管理后台
- 资源中心对普通用户可见（只读，admin 有全部 CRUD 权限）
- 员工管理 + 用户管理插入主导航（仅 admin 可见）
- 首页统计修复（并行调用 /employees + /catalog + /conversations）

---

## 0.2.0 (2026-07-24)

### 新增
- 前端 Vue 3 + Vite + Naive UI 重构
- 对话 SSE 流式响应
- HITL 审批决策
- 执行过程追踪（traces）
- 用户 - 员工分配机制
- 资源中心（技能/工具/知识库/SOP/连接器 CRUD）

### 修复
- 软删除各实体级联关系
- 登录限流
- XSS 消毒

---

## 0.1.0 (2026-07-22)

首次提交：myagents 数字员工平台初始代码。
基于 deepagents + LangGraph 的数字员工运行平台，含小苏（客服）和小数（数据分析师）两个员工模板。