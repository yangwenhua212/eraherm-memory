# syntax=docker/dockerfile:1
#
# EraHerm-Memory — 容器镜像（单阶段，python:3.13-slim）
#
# ⚠️ 这个容器**没有 ERAHERM_API_TOKEN 就起不来**，不是配置建议而是硬性事实：
#    Dockerfile 里 `ENV ERAHERM_HOST=0.0.0.0`（容器内必须监听所有网卡，否则宿主
#    的端口映射打不进来），而 app/main.py 在 import 期就读 settings 并调用
#    app.security.exposure_problem()：只要绑定地址不是回环（127.0.0.1/localhost/::1）
#    且 ERAHERM_API_TOKEN 未配置（或仍是占位值），create_app() 直接 raise RuntimeError
#    → 进程退出，容器反复重启。
#    占位值同样视为「未配置」：dev-admin-token / dev-api-token / changeme /
#    change-me / CHANGE_ME / your-admin-token / your-api-token / test / 空串。
#    生成真实密钥：python -c "import secrets;print(secrets.token_urlsafe(32))"
#    逃生舱（不推荐）：ERAHERM_ALLOW_INSECURE_PUBLIC=true，仅当前置网关已做鉴权时使用。
#
# 另外两个必须知道的运行时事实：
#   1) 有 API token 时，/v1/* 除 GET /v1/health 外全部要求 X-API-Token（或
#      Authorization: Bearer）；/v1/admin/* 还要 X-Admin-Token，且
#      ERAHERM_ADMIN_TOKEN 未配置时 admin 端点一律 503（fail-closed）。
#      → 下面的 HEALTHCHECK 打的是 /v1/health，**不需要 token**。
#   2) SQLite 数据落在 ERAHERM_DATA_DIR，本镜像固定为 /data 并声明 VOLUME；
#      数据库 URL 一并改到 /data，保证 alembic 与 API 进程写同一个文件。

FROM python:3.13-slim

# 可选依赖开关（见 pyproject.toml 的 [project.optional-dependencies]）：
#   mcp,scheduler       默认：给 eraherm-mcp / eraherm-consolidate 与夜间整理
#   redis,qdrant,neo4j  多实例 / 大规模召回 / 图查询时才加
#   fastembed           本地中文向量；会拉 onnxruntime（200MB+）并在首次使用时
#                       下载模型 —— 刻意**不**进默认镜像，见 docs/DEPLOYMENT_DOCKER.md
# 例：docker build --build-arg EXTRAS="mcp,scheduler,fastembed" -t eraherm-memory .
ARG EXTRAS="mcp,scheduler"

# 注意：ERAHERM_DATABASE_URL 必须与 ERAHERM_DATA_DIR 保持一致 ——
# `alembic upgrade head` 与 API 进程要指向同一个 SQLite 文件，否则迁移建的表
# 落在另一个空库里，等于白跑。（这里是四个斜杠：sqlite:// + 绝对路径 /data/...）
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    ERAHERM_HOST=0.0.0.0 \
    ERAHERM_DATA_DIR=/data \
    ERAHERM_DATABASE_URL=sqlite:////data/eraherm.db

# libgomp1: onnxruntime(fastembed 额外依赖) 在 slim 上需要它；其余依赖装 wheel 即可，
# 默认不透传 gcc/build-essential，若你的 EXTRAS 里出现需要现场编译的包再按需补。
RUN apt-get update \
 && apt-get install --no-install-recommends -y libgomp1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 独立 venv，不污染系统 Python（PATH 已把 /opt/venv/bin 前置）。
RUN python -m venv "$VIRTUAL_ENV"

# 先只装依赖（--no-deps 跳过本包自身），让这层在源码变动时仍能命中缓存。
COPY pyproject.toml README.md LICENSE ./
COPY app ./app
COPY sdk ./sdk
COPY evals ./evals
RUN pip install --upgrade pip setuptools wheel \
 && pip install --no-deps -e . \
 && pip install ".[${EXTRAS}]"

# 运行期/迁移需要的其余文件
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY demo ./demo
COPY mcp.json ./mcp.json

# 非 root 运行。先建 /data（VOLUME 首次创建时会继承镜像内该目录的属主），
# 再切用户 —— 否则 eraherm 用户无法在 /data 建库文件。
RUN groupadd --system eraherm \
 && useradd --system --gid eraherm --create-home --home-dir /home/eraherm eraherm \
 && mkdir -p /data \
 && chown -R eraherm:eraherm /data /app
USER eraherm

VOLUME ["/data"]
EXPOSE 8000

# slim 里没有 curl/wget（也没装），所以用标准库 urllib。GET /v1/health 是公开路由，
# 不需要 X-API-Token；只关心能否连上并返回 2xx/3xx/4xx（服务已起来即可）。
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=4); sys.exit(0 if r.status < 500 else 1)"]

# 不依赖「应用启动时顺手建表」：先跑迁移再起服务。
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
