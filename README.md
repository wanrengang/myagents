# UniEmployee 数字员工平台

基于 **deepagents**（LangGraph）的多租户数字员工运行平台，跑通五层能力模型
（Employee → Workflow/SOP → Skill → Connector → Tool）+ HITL 审批 + 跨会话记忆 +
**执行过程 Trace** 可观测，并配套员工/资源/用户的可视化管理后台。

> 设计文档：`demo-tech-design.md`（v0.2，在 WorkBuddy 工作区）

## 快速开始

```bash
cd /Users/wrg/coding/myagents
cp .env.example .env            # 填入 OPENAI_API_KEY / JWT_SECRET 等
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8787
# 浏览器打开 http://localhost:8787
```

`.venv` 已随包建好（Python 3.13）。如需重建：

```bash
python3.13 -m venv .venv
.venv/bin/pip install --no-cache-dir -r requirements.lock.txt   # 完全可复现
```

## 功能一览

- **数字员工**：页面化配置人设 / 技能 / 工具 / 知识库 / SOP / 连接器，运行时以库为准。
- **跨会话记忆**：按 `(user_id, employee_id)` 隔离，落盘 `store.db`，重启不丢。
- **HITL 审批**：工作流中途中断等人工批准（如退款），批准后流程继续。
- **Trace 可观测**：每次对话/审批恢复 = 一条 run，记录 LLM / 工具调用的输入输出、耗时、token；
  入口：对话页右上角「执行过程」、历史页每行「执行过程」、`/trace.html?run=<run_id>`。
- **多用户 + 鉴权**：JWT 登录，普通用户仅见被分配的员工；admin 管后台。
- **软删除**：会话 / 员工 / 技能等实体均软删（保留正文便于恢复），关联表硬删。

## 目录与数据

```
app/
├── main.py            # FastAPI 网关：SSE 流 / 审批恢复 / 鉴权 / 中间件 / /health
├── compiler.py        # ★ 编译层：spec → create_deep_agent
├── runtime.py         # agent 缓存 + checkpointer + store + 用户记忆
├── catalog.py         # 目录库 catalog.db（员工/技能/工具/知识库/SOP/连接器）
├── conversations.py    # 会话元数据 conversations.db
├── traces.py          # 执行过程 traces.db（runs + events）
├── auth.py            # 密码哈希(bcrypt) + JWT + 鉴权依赖
├── approvals.py       # HITL 审批单
├── paths.py           # 统一数据目录 / DB 路径（受 APP_DATA_DIR 控制）
├── logging_setup.py   # 结构化日志 + 请求ID
├── errors.py          # 全局异常处理（未捕获异常 → 干净 JSON 500）
├── employees/*.yaml   # 员工种子定义（仅首次启动写入 catalog.db）
├── static/           # 前端页面（home/login/chat/admin/resources/history/trace/...）
├── tools/  workflows/  connectors/   # Tool / Workflow / Connector 实现
└── data/  (运行时生成的 SQLite 库与看板，gitignore)
skills/               # 内置技能（git）
skills-custom/        # 上传/自定义技能（gitignore）
workspace/data/{user_id}/   # 数据分析师生成的看板，按用户隔离
```

SQLite 库（均在数据目录下，默认项目根，容器化指向挂载卷）：

| 文件 | 作用 |
|------|------|
| `catalog.db` | 员工 / 技能 / 工具 / 知识库 / SOP / 连接器 目录 |
| `conversations.db` | 会话元数据（标题、归属、预览、计数）|
| `demo.db` | LangGraph checkpointer（对话状态 / 消息历史）|
| `store.db` | 长期记忆（按 user+员工隔离）|
| `traces.db` | 执行过程追踪 |

## 安全基线

- 所有接口必须携带 `Authorization: Bearer <token>`，匿名（含原 `X-User-Id` 回落）一律 401。
- 登录失败返回 401；同 `(IP, 用户名)` 60 秒内失败 ≥5 次限流 429（60 秒）。
- `JWT_SECRET` **必须**在 `.env` 配置为长随机串（否则启动告警且可被伪造 token）；
  更换后所有旧 token 立即失效。
- 调试接口 `/api/debug/memory` 仅 admin。
- admin 仍用默认密码 `admin123` 时，登录响应带 `must_change_password=True`，前端强制改密。
- 前端 LLM 输出经 `sanitizeHtml()` 消毒，防 XSS。
- **务必改默认管理员密码**。

## 运维

### 环境变量（`.env`）

| 变量 | 默认 | 说明 |
|------|------|------|
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `MODEL_NAME` | — | 模型（OpenAI 兼容协议）|
| `JWT_SECRET` | `change-me-in-prod`（告警）| JWT 签名密钥，**必须改** |
| `JWT_EXPIRE_HOURS` | `24` | token 有效期 |
| `LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR |
| `LOG_FILE` | 空（仅控制台）| 日志文件路径（建议挂卷）|
| `APP_DATA_DIR` | 项目根 | SQLite 库与运行时数据目录（容器持久化）|
| `APP_VERSION` | `0.3.0` | 打印在 /health 与日志，便于多实例定位 |

### 健康检查

`GET /health`（无需登录）返回：

```json
{
  "status": "ok",
  "version": "0.3.0",
  "timestamp": "2026-07-25T...Z",
  "databases": {"catalog.db": "ok", "conversations.db": "ok", "...": "ok"}
}
```

`status` 为 `degraded` 表示有库连不上；容器 `HEALTHCHECK` 已配置。

### 备份

```bash
# 备份 5 个库到 ./backups/myagents-<时间戳>.tar.gz，保留最近 7 份
BACKUP_KEEP=7 ./scripts/backup.sh
# 也可指定数据目录与备份目录
./scripts/backup.sh /path/to/data /path/to/backups
```

建议 crontab 每日跑一次（见脚本头部注释）。SQLite 有 `-wal/-shm` 临时文件，
备份前短暂停服可获得一致性快照。

### 日志

结构化输出，每行含 `时间 级别 [模块] [rid=请求ID] 消息`。
请求 ID 串起一次请求内的全部日志；第三方库（uvicorn.access/langchain/httpx）
默认降噪到 WARNING。

### Docker 部署

```bash
# 构建并后台运行（数据/自定义技能/看板均挂载卷，重启不丢）
docker compose up -d --build
# 健康检查：curl http://localhost:8787/health
```

`docker-compose.yml` 通过 `env_file: .env` 注入密钥（`.env` 不进镜像、不提交仓库）。
如需自定义数据卷位置，改 `APP_DATA_DIR` 并相应调整挂载点。

## 测试

```bash
# 后端单测（pytest，夹具自动把 catalog/conversations 换成临时库）
.venv/bin/python -m pytest tests/ -v
# 真实联网/外部依赖用 @pytest.mark.skipif 守护（如无 API key 跳过）
```

## 已知边界 / 后续

- 单进程内存实现：登录限流、会话热映射、agent 缓存均在进程内，多副本需换 Redis/共享存储。
- 软删除已做，暂无回收站 UI；部分删除仅 API 层。
- 强制改密目前前端拦截，API 层未硬阻断（后续可加中间件）。
- 多租户 `tenant_id` 已预留字段，隔离逻辑待做。
