---
name: project-directory-restructure
description: 按专业项目标准重新组织目录结构，分离源码、数据、配置
metadata:
  type: project
status: pending
---

## 当前问题

- 5 个 SQLite 数据库文件散落在项目根目录（catalog.db / conversations.db / demo.db / store.db / traces.db）
- 源码在 app/，前端在 frontend/，没有统一的 src/ 入口
- `.env` 在根目录（.gitignore 排除了，但结构上不应该）
- macOS 的 `.DS_Store`、历史 zip 压缩包等垃圾文件污染根目录
- 备份文件 backups/、日志 logs/ 也在根目录

## 目标结构

```
myagents/
├── src/                          # 统一源码目录
│   ├── server/                   #   后端（原 app/）
│   │   ├── main.py
│   │   ├── compiler.py
│   │   ├── runtime.py
│   │   ├── catalog.py
│   │   ├── auth.py
│   │   ├── approvals.py
│   │   ├── conversations.py
│   │   ├── traces.py
│   │   ├── errors.py
│   │   ├── paths.py
│   │   ├── logging_setup.py
│   │   ├── spec.py
│   │   ├── employees/            #     YAML 种子
│   │   ├── tools/
│   │   ├── workflows/
│   │   └── connectors/
│   └── web/                      #   前端（原 frontend/）
│       ├── src/
│       ├── dist/
│       └── package.json
├── data/                         # 运行时数据（gitignore）
│   ├── db/                       #   SQLite 数据库
│   │   ├── catalog.db
│   │   ├── conversations.db
│   │   ├── demo.db
│   │   ├── store.db
│   │   └── traces.db
│   └── workspace/                #   分析工作区
│       ├── data/
│       └── tmp/
├── config/                       # 配置文件
│   └── .env.example
├── docs/                         # 文档（原 .docs/）
├── scripts/                      # 运维脚本
├── tests/                        # 测试
├── skills/                       # 技能
├── skills-custom/                # 自定义技能（gitignore）
├── logs/                         # 日志（gitignore）
├── backups/                      # 备份（gitignore）
├── .gitignore
├── README.md
├── CLAUDE.md
├── TODO.md
├── pyproject.toml                # Python 项目元数据
├── requirements.txt
├── requirements.lock.txt
├── Dockerfile
└── docker-compose.yml
```

## 改动内容

1. **app/ → src/server/** — 所有 Python 后端代码，改内部 import 路径
2. **frontend/ → src/web/** — 前端代码
3. **新建 data/db/** — `APP_DATA_DIR` 默认值改为 `data/db`，所有 `.db` 文件走这里
4. **.docs/ → docs/** — 项目文档归入 docs/
5. **清理根目录** — 移除 `.DS_Store`、历史 zip 包，确保 `.gitignore` 覆盖所有运行时产物
6. **`APP_DATA_DIR` 默认值** — 改 `paths.py` 为 `DATA_DIR = ROOT / "data" / "db"`

## 迁移策略

- 先改 `paths.py` 中的默认数据目录（影响最小，只需确认 data/db/ 存在）
- 再改目录结构（需要更新 Dockerfile、docker-compose.yml、所有 import 路径）
- 最后测试全链路：启动 → seed → 对话 → 审批 → 追踪

## Why

- 数据文件不该和源码混在一起
- Docker 部署时挂载 data/ 卷即可持久化全部数据，不需要逐个文件配置
- 统一 src/ 入口符合行业惯例，降低新成员理解成本
- `.gitignore` 只需忽略 data/、logs/、backups/ 等几个目录，不再需要逐个数据库文件列出

## How to apply

安排在代码结构整理（codebase-restructure.md）之后或一起做。先改 paths.py 的数据目录默认值（改动最小，立即生效），再改目录结构。每次改完跑 pytest + 手动验证。