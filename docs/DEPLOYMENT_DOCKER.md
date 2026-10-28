# Docker 部署（EraHerm-Memory）

> 面向「用容器跑一个自己的记忆后端」的单机部署。后端选型与升级顺序仍以
> [DEPLOYMENT.md](DEPLOYMENT.md) 为准，信任边界以 [SECURITY.md](../SECURITY.md) 为准。
> 本文只管容器：怎么起、怎么认证、怎么备份、什么时候**不要**加 worker。

---

## 1. 快速开始

```bash
# 1) 准备配置
cp .env.example .env          # Windows: copy .env.example .env

# 2) 生成一个真实密钥，写进 .env 的 ERAHERM_API_TOKEN
python -c "import secrets;print(secrets.token_urlsafe(32))"

# 3) 起服务（构建 + 后台运行）
docker compose up -d

# 4) 看健康状态（/v1/health 是公开路由，不需要 token）
curl http://127.0.0.1:8000/v1/health
```

`docker compose` 只把端口绑到宿主回环 `127.0.0.1:8000`，因此默认形态下
**即使忘了配 token，别人也连不上**。要对内网/公网提供服务，见第 3 节。

镜像默认 `EXTRAS="mcp,scheduler"`（见 [Dockerfile](../Dockerfile)）。要自定义：

```bash
docker compose build --build-arg EXTRAS="mcp,scheduler,redis"
# 或写进 .env：ERAHERM_EXTRAS=mcp,scheduler,redis
```

---

## 2. 两个必配的密钥，以及「起不来」是故意的

| 变量 | 作用 | 不配的后果 |
|------|------|-----------|
| `ERAHERM_API_TOKEN` | `/v1/*` 的共享密钥（`/v1/health` 除外） | **进程拒绝启动**（容器反复重启） |
| `ERAHERM_ADMIN_TOKEN` | `/v1/admin/*`（consolidate / watchdog / reembed / l3 dump） | 不启动，但 admin 端点**一律 503**（fail-closed） |

为什么容器里必须配 `ERAHERM_API_TOKEN`：

- 容器内必须 `ERAHERM_HOST=0.0.0.0`（否则宿主的端口映射打不进来），这是**非回环**地址；
- `app/main.py` 在 import 期就读 settings 并检查暴露面（`app/security.py`）：
  **非回环绑定 + `ERAHERM_API_TOKEN` 未配置 = `RuntimeError`，进程直接退出**；
- 容器里没有「等一等就好了」：`docker compose ps` 会看到它不断重启，
  `docker compose logs eraherm` 里能看到那段「拒绝启动：…」的解释。

占位值同样算「未配置」，别拿它们当密钥：
`dev-admin-token`、`dev-api-token`、`changeme`、`change-me`、`CHANGE_ME`、
`your-admin-token`、`your-api-token`、`test`、空串。

`docker compose` 这一层也会提前拦一次：`docker-compose.yml` 里写的是
`ERAHERM_API_TOKEN: "${ERAHERM_API_TOKEN:?set ERAHERM_API_TOKEN in .env}"`，
漏配时 compose 自己就报 `set ERAHERM_API_TOKEN in .env`，不用等容器起来才发现。

逃生舱（**不推荐**）：`ERAHERM_ALLOW_INSECURE_PUBLIC=true`。只在你前面已经有
网关做鉴权时才用；`ERAHERM_API_TOKEN` 是单租户共享密钥，它不区分 `user_id`
（多租户隔离未实现）——详见 [SECURITY.md](../SECURITY.md)。

---

## 3. 客户端怎么认证

配了 token 后，**除 `GET /v1/health` 外的所有 `/v1/*` 都要带**：

```bash
# 推荐：X-API-Token
curl -H "X-API-Token: $ERAHERM_API_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"content":"数据库用 PostgreSQL","pinned":true}' \
     http://127.0.0.1:8000/v1/memories

# 也支持：Authorization: Bearer
curl -H "Authorization: Bearer $ERAHERM_API_TOKEN" http://127.0.0.1:8000/v1/metrics

# admin 端点还要再多一个头
curl -H "X-API-Token: $ERAHERM_API_TOKEN" -H "X-Admin-Token: $ERAHERM_ADMIN_TOKEN" \
     -X POST http://127.0.0.1:8000/v1/admin/watchdog
```

绑到回环时，宿主上的客户端直接用 `http://127.0.0.1:8000` 即可。
要让局域网/公网访问：把 `docker-compose.yml` 的 `ports` 改成 `"8000:8000"`
（或绑定内网 IP），并**务必**在其前面放反向代理做 TLS 与限流 ——
镜像本身不带 TLS，也没有速率限制，`content` 也没有长度上限（见 SECURITY.md）。

---

## 4. 数据库迁移

镜像的 `CMD` 是：

```sh
alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000
```

也就是**每次启动都先跑迁移再起服务**，正常情况下你不需要手动做任何事。
（应用本身也会在运行时建表，但部署镜像不依赖这一点。）

手动执行 / 排查：

```bash
# 只跑迁移
docker compose run --rm --entrypoint sh eraherm -c "alembic upgrade head"

# 看当前版本 / 历史
docker compose run --rm --entrypoint sh eraherm -c "alembic current"
docker compose run --rm --entrypoint sh eraherm -c "alembic history"

# 启动日志（迁移失败会在这里显示）
docker compose logs -f eraherm
```

容器里刻意对齐了两个路径变量，避免「迁移建的表和 API 读的库不是一个文件」：

```yaml
ERAHERM_DATA_DIR: "/data"
ERAHERM_DATABASE_URL: "sqlite:////data/eraherm.db"   # 注意是四个斜杠
```

> `alembic.ini` 里的 `sqlalchemy.url` 只是兜底默认值；运行时以 `ERAHERM_DATABASE_URL`
> 为准。所以**不要**在 `docker compose exec` 里手动 `cd` 到别处再跑 alembic，
> 那样会按 `alembic.ini` 的相对路径另建一个库。

---

## 5. 备份与恢复 `/data`

`/data` 里是全部身家：SQLite 库（`eraherm.db`）、L3 归档（`/data/l3`）、
以及启用 fastembed 时的模型缓存。它在 compose 里是**命名卷** `eraherm-data`。

SQLite + WAL 的注意点：**要么停容器，要么用 SQLite 自己的备份机制**，
不要直接 `cp` 正在写入的库文件。

```bash
# 方式 A（最稳）：停服务 → 打包整卷 → 再起
docker compose stop eraherm
docker run --rm -v eraherm-memory_eraherm-data:/data -v "$PWD:/backup" alpine \
  tar czf /backup/eraherm-data-$(date +%Y%m%d).tar.gz -C /data .
docker compose start eraherm

# 方式 B：不停服务，用 SQLite 自己的 backup API 做一致性快照
docker compose exec eraherm python -c "import sqlite3;s=sqlite3.connect('/data/eraherm.db');d=sqlite3.connect('/data/backup-eraherm.db');s.backup(d);d.close();s.close()"
# 快照写在卷里了，再搬到宿主（用一次性容器挂载该卷，不依赖镜像里有别的工具）：
docker run --rm -v eraherm-memory_eraherm-data:/data -v "$PWD:/backup" alpine \
  cp /data/backup-eraherm.db /backup/backup-eraherm.db
```

卷名以 `docker volume ls` 实际输出为准（compose 默认前缀是项目目录名，
所以上面用的是 `eraherm-memory_eraherm-data`；Windows 上 `"$PWD"` 换成
`"${PWD}"` 或绝对路径 `D:\backup`）。

恢复：停容器 → 用备份覆盖卷内容 → 起容器（`alembic upgrade head` 会自动补迁移）。
L3 归档另有 `eraherm-l3-dump` 之类的手动导出路径，见 [DEPLOYMENT.md](DEPLOYMENT.md)。

---

## 6. ⚠️ 单写者：不要加 `--workers`，也不要跑多副本

默认栈是 **SQLite 单文件 + 进程内 L1（dict）+ 进程内 scheduler**。所以：

- **不要**改成 `uvicorn ... --workers 4`（compose 里也别加 `--scale`）：
  - 每个 worker 各持一份 L1，一个进程写入、另一个进程看不到，缓存不一致；
  - `ERAHERM_CONSOLIDATION_ENABLED=true` 时，每个 worker 都会起一份夜间整理任务，
    同一条记忆被并发「整理」是破坏性操作（软删/遗忘/压缩后删原文，且没有恢复接口）；
  - SQLite 只有一个写者，多进程写入直接锁冲突（`database is locked`）。
- **共享 L1 只上 Redis 是不够的**：主库仍是单文件 SQLite，写者仍然只有一个。
- 真要多实例：先换主库（Postgres，目前尚未实现），再按
  [DEPLOYMENT.md](DEPLOYMENT.md) 的触发条件逐项上 Redis / Qdrant / Neo4j。
- 需要夜间整理又不想让它拖累请求：不要开多 worker，改用独立进程跑
  `eraherm-consolidate`（这也是 `.env.example` 里的建议）。

即：**一个容器 = 一个写者**，扩展先从「换后端」开始，不是从「加 worker」开始。

---

## 7. 镜像里刻意**没有**什么

- **没有 `fastembed` / `onnxruntime`**（除非你显式 `EXTRAS` 加上）：
  onnxruntime 约 200MB+，且首次使用还会下载模型权重。
  默认镜像的 embedding 是 `hashing` —— **离线可用，但中文语义召回弱**，
  只适合 Demo/CI。要生产可用：`--build-arg EXTRAS="mcp,scheduler,fastembed"`
  并把 `ERAHERM_EMBEDDING_BACKEND=fastembed`（模型缓存会落在 `/data`）。
- **没有 GPU 支持**：基础镜像是 `python:3.13-slim`，onnxruntime 走 CPU；
  要 GPU 得自己换基础镜像（`nvidia/cuda` + `onnxruntime-gpu`），不在本镜像范围内。
- **没有 curl / wget**：`HEALTHCHECK` 用的是标准库 `urllib`，你在容器里
  想手动探活就用 `python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/v1/health').status)"`。
- **没有 TLS、没有反向代理、没有速率限制**：对外提供服务时请在容器前面放网关。
- **没有 Redis / Qdrant / Neo4j**：`docker-compose.yml` 里有注释掉的**可选**服务，
  默认关闭；一次全开会让部署复杂度暴涨，按触发条件逐个开。
- **没有编译工具链**（默认）：依赖都走预编译 wheel。若你的 `EXTRAS` 命中需要
  现场编译的包，再往 Dockerfile 的 `apt-get install` 里加 `build-essential`。

---

## 8. 常用运维命令

```bash
docker compose ps                      # 看健康状态（healthy / restarting）
docker compose logs -f eraherm         # 跟随日志（JSON 格式，默认 ERAHERM_JSON_LOGS=true）
docker compose exec eraherm sh         # 进容器排查
docker compose pull && docker compose up -d --build   # 更新镜像
docker compose down                    # 停止（卷保留，数据不丢）
docker compose down -v                 # ⚠️ 连数据卷一起删，记忆全没
```

相关文档：[DEPLOYMENT.md](DEPLOYMENT.md)（后端选型与升级顺序）、
[SECURITY.md](../SECURITY.md)（信任边界与已知短板）、
[README](../README.md#认证与暴露面0102-起)（认证与暴露面速查）。
