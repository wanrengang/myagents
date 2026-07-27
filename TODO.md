# 待办事项总清单

> 更新时间：2026-07-26
> 按优先级排列

## P0 阻断性缺陷

- [ ] **#1 前端路由修复** — 所有 `router.push(\`/path\`)` 改为 `router.push({name: 'xxx'})`，已改 HomeView/HistoryView/ChatView/TraceView，检查是否还有遗漏
- [ ] **#2 首页统计修复** — `/api/catalog` 不返回 employees/conversations，已改为并行调 3 个接口
- [ ] **#3 退款审批不可用** — inner_thread 审批从未调 `resume_refund()`，审批恢复路径断裂
- [ ] **#4 XSS 消毒加固** — `sanitizeHtml` 只拦 `data:text/html`，`data:text/javascript` 等可绕过

## P1 功能缺陷

- [ ] **#5 审批内存实现 + 无超时 + 无鉴权** — approvals.py 纯内存，重启全丢；无超时自动拒绝；decide 端点无鉴权
- [ ] **#6 强制改密无 API 层阻断** — must_change_password 标记存在但不检查
- [ ] **#7 MCP stdio 子进程关闭时未清理** — lifespan 退出时没 shutdown MCP client
- [ ] **#8 `reconstruct()` 工具调用结果匹配靠顺序** — 并行工具执行时结果会配错
- [ ] **#9 `create_ticket` assert 无异常处理** — LLM 传非法 urgency 值时抛 AssertionError
- [ ] **#10 `start_refund` 内层 thread ID 用 hash()** — PYTHONHASHSEED 导致不同进程间 thread id 不同
- [ ] **#11 SSE Fetch 无 AbortController** — 服务端挂起时连接不释放
- [ ] **#12 无 CI/CD 流水线** — 无 GitHub Actions
- [ ] **#13 无 .dockerignore** — 构建上下文含 .venv/.git/node_modules

## P2 优化改进

- [ ] **#14 审批 API 加鉴权** — decide 端点没有 Depends(auth.get_current_user)
- [ ] **#15 employee_of() 空目录抛 IndexError** — discover_employees()[0] 无前置检查
- [ ] **#16 SSE 错误消息泄漏异常细节** — f"{type(e).__name__}: {e}" 泄漏给前端
- [ ] **#17 recover_conversations() 无上限** — 启动时全表扫描线程
- [ ] **#18 run_python 无输入限制** — 任意长度代码无大小限制
- [ ] **#19 recover_conversations() 技能匹配靠字符串搜 blob** — 可能误匹配
- [ ] **#20 token 在 localStorage 中** — 应改用 HttpOnly cookie
- [ ] **#21 容器以 root 运行** — Dockerfile 无 USER 指令
- [ ] **#22 登录页泄露默认凭据** — 显示"默认管理员 admin / admin123"

## P3 技术债务

- [ ] **#23 将 kb_search 从内置闭包改为外挂 MCP 连接器** — 解耦知识库引擎，升级向量检索时不改主系统代码。知识库内容变更即时生效。详见 `knowledge-base/kb-mcp-extraction.md`
- [ ] **#24 知识库检索升级为向量检索** — 替换当前的关键词匹配
- [ ] **#25 代码结构渐进式整理** — 拆分 main.py(1050行) / catalog.py(976行)，提取独立模块。详见 `knowledge-base/codebase-restructure.md`
- [ ] **#26 技能编辑接口（后端）** — 当前管理后台只能读 SKILL.md，没有写接口
- [ ] **#27 技能内容变更后不生效的问题** — 改了 SKILL.md 需要 invalidate 触发重编译，但当前没有触发机制
- [ ] **#28 MCP server 连接器定义和连接器实现的关系需要文档化** — connectors 表的 config 字段和 app/connectors/ 下的文件怎么对应
- [ ] **#29 tools/kb.py 中独立的 kb_search 函数是死代码** — 运行时用 compiler.py 的 make_kb_search 闭包

## P4 新增功能

- [ ] **#30 软删除回收站 UI** — 各实体软删已做，缺管理页面恢复
- [ ] **#31 多租户隔离** — tenant_id 已预留，缺查询层过滤
- [ ] **#32 对话导出（Markdown/纯文本）**
- [ ] **#33 token 自动刷新机制**
- [ ] **#34 技能版本管理**
- [ ] **#35 管理员仪表盘**
- [ ] **#36 用户自注册**
- [ ] **#37 按用户隔离技能** — 当前所有用户共享同一员工的技能
- [ ] **#38 修改配置后主动预热** — 当前靠用户首次消息触发重编译，可改成保存后主动调 get_agent()
- [ ] **#39 界面新增工具** — 设计工具模板（API 调用/Webhook/脚本），通过 tools 表 config 字段动态生成 @tool 函数

## ✅ 已完成

- [x] **HomeView 路由修复** — 所有 router.push 改为 name 跳转
- [x] **MainLayout 菜单闪烁问题** — 移除 transition + :key，改为 keep-alive 缓存组件
- [x] **HistoryView 路由修复** — /chat?conv= 和 /trace?conv= 改为 name 跳转
- [x] **ChatView "执行过程"按钮** — 从 href 改为 window.open(router.resolve())
- [x] **SOP 可展开查看内容** — catalog() 返回 content 字段 + 前端展开/收起
- [x] **知识库条目详情弹窗** — 每条目加「查看详情」按钮
- [x] **知识库公共 API** — 新增 GET /api/knowledge-bases/{id}/entries（普通用户可读）
- [x] **Trace 默认折叠** — traceExpanded = false
- [x] **资源中心导航对普通用户可见** — 从 adminNavOptions 移到 mainNavOptions
- [x] **资源中心按钮权限控制** — 普通用户只能查看，admin 有新建/编辑/删除
- [x] **资源中心知识库条目 API 路径修复** — /admin/kbs/ → /admin/knowledge-bases/
- [x] **TraceView 路由修复** — $router.push('/history') → {name:'history'}
- [x] **历史页分页组件** — 封装 PaginationBar 可复用组件，独立 n-pagination 替代 data-table prop
- [x] **员工管理移入主导航** — adminOnlyNavOptions 插入 mainNavOptions 中，排在资源中心前面
- [x] **Skill 内容查看入口** — 每技能卡片加「查看内容」按钮 + 弹窗显示 SKILL.md
- [x] **Skill 编辑加内容字段** — 编辑弹窗新增「SKILL.md 内容」textarea
- [x] **小苏/小数内容丰富** — 知识库 6→30 条、订单 3→10 个、客户 2→6 个、销售数据 24→60 行
- [x] **StaffDeck supervisor 占端口问题排查** — 根因是 `dev_supervisor.py` 孤儿进程抢 5173
- [x] **ChatView useRouter 未导入** — 导致 openTrace 报错
- [x] **ChatView route 重复声明** — const route 定义两次导致 build 失败
- [ ] **#41 Token 统计按用户隔离** — 首页 token 统计：管理员看全局，普通用户只看自己的消耗
- [x] **ChatView useRouter 未导入** — 导致 openTrace 报错
- [x] **ChatView route 重复声明** — const route 定义两次导致 build 失败
- [x] `reactive` **未导入** — HistoryView 从 import 中误删了 reactive