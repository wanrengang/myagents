# 数字员工平台（myagents）运行镜像
# 数据持久化：容器内的 /app/data 应挂载为卷（见 docker-compose.yml），
# 这样 catalog.db / conversations.db / demo.db / store.db / traces.db 在重启后保留。
FROM python:3.11-slim

# 避免字节码写入、保证日志即时 flush、pip 不缓存
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_DATA_DIR=/app/data \
    PORT=8787 \
    LOG_LEVEL=INFO

WORKDIR /app

# 系统依赖：编译 bcrypt/cryptography 等可能用到（纯 SQLite 运行不一定需要，但装上更稳）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖（利用镜像层缓存）：requirements.lock.txt 是 pip freeze 的完整可复现清单
COPY requirements.lock.txt ./
RUN pip install --upgrade pip && pip install -r requirements.lock.txt

# 再拷代码
COPY . .

# 创建数据 / 日志目录；.env（含密钥）不要 COPY，运行时用卷或 -e 注入
RUN mkdir -p /app/data /app/logs /app/skills-custom /app/workspace/data

EXPOSE 8787

# 容器探针：连不上 /health 即视为不健康
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD curl -fsS http://localhost:8787/health || exit 1

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
