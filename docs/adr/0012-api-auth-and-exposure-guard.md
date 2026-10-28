# ADR 0012：HTTP 面认证与「无认证不得对外」启动守卫

- 状态：Accepted
- 日期：2026-10-09
- 取代/影响：`app/security.py`、`app/api/auth.py`、`app/main.py`、`app/config.py` 的
  `host` / `admin_token` 默认值

## 上下文

0.10.1 及之前，HTTP 面**除 `/v1/admin/*` 外没有任何认证**，用户身份完全由调用方自报：

```http
POST /v1/recall
{"user_id": "别人的 user_id", "query": "..."}
```

`user_id` 直接来自请求体或 `X-User-Id`（`app/api/routes.py`），而隔离只是
「按调用方自报的 user_id 过滤」（`app/adapters/sqlite_vector_store.py`、
`app/memory/service.py`）。于是任何能访问端口的人都可以：

- 读任意用户的记忆原文（`POST /v1/recall` 把 `content` 原样回传）
- 往任意 `user_id` 写入内容 —— 而受害 Agent 后续 recall 会把它当作事实注入上下文
  （**记忆投毒 / Prompt Injection**）
- 用 `memory_id` 改别人的 pin 状态（`/v1/memories/pin`，无归属校验）
- 用 `/v1/feedback` 的 `related_memory_ids` 反复降权别人的记忆，直到被 consolidate 遗忘

同时：

1. `admin_token` 默认值是 `dev-admin-token`，且 `_require_admin` 在 `settings` 缺失时
   **fallback 到同一个默认值**（fail-open）。它保护的是全库导出（`/v1/admin/l3/dump`）、
   全库删改（`/v1/admin/consolidate`）和用户枚举（`/v1/admin/watchdog`）。
2. `host` 默认 `0.0.0.0`，README 又引导直接 `uvicorn app.main:app --port 8000`。
3. `SECURITY.md` 承认「无完整用户鉴权、依赖网络隔离」——但默认配置本身就把网络隔离
   这个前提打破了。

一句话：**默认配置 = 一个匿名可读写、可投毒、可全库导出的记忆库。**

## 决策

### 1. 引入 `ERAHERM_API_TOKEN`（可选，但公开绑定时必需）

- 设置了它：`/v1/*` 除 `/v1/health` 外一律要求 `X-API-Token: <token>`
  （兼容 `Authorization: Bearer <token>`；其它 scheme 忽略）。
- 没设置：不启用认证，**但只有绑定回环地址才允许启动**（见第 2 条）。

选择共享密钥而不是完整用户体系，是因为：本项目的当前定位是「单机 / 个人 AI OS 的
记忆内核」，引入 OAuth/JWT/用户表会把内核变重，且和 ADR 0001（内核而非完整 Agent）冲突。
共享密钥能立刻消掉「匿名全库读写」，同时不假装已经解决了多租户。
**已知限制：设置 token 后仍是单租户语义 —— 它认证「谁可以访问这个实例」，
不认证「你可以访问哪个 user_id」。多租户隔离仍未实现，见「后续」。**

### 2. 启动守卫：无认证 + 可达网络 = 拒绝启动

`app/security.py:exposure_problem()` 在 `create_app()` 里执行：

- `host` 是回环（`127.0.0.1` / `::1` / `localhost`）→ 放行（本机默认形态）
- `host` 不是回环且 `api_token` 未配置 → 抛 `RuntimeError`，进程起不来
- `ERAHERM_ALLOW_INSECURE_PUBLIC=true` → 显式覆盖（保留给「我知道我在干什么」的场景，
  比如已经有前置网关注入鉴权的部署）

**默认 `host` 从 `0.0.0.0` 改成 `127.0.0.1`。** 无认证时这是唯一安全的取值，
而且 uvicorn 自己的默认值也是 `127.0.0.1`，`README` 里的 `uvicorn app.main:app`
命令本来就不需要 `0.0.0.0`。

这是**破坏性**变更：已有部署如果设了 `ERAHERM_HOST=0.0.0.0` 而没配 token，升级后会启动失败。
我们选择「启动失败 + 明确的修复指引」，而不是「启动成功 + 一条容易被忽略的 warning」——
安全默认值不该依赖运维读日志。

### 3. `admin_token` fail-closed

- 默认值由 `dev-admin-token` 改为空。
- 空 / 占位值（`PLACEHOLDER_TOKENS`）视为未配置 → `/v1/admin/*` 一律 **503
  `admin_disabled`**，永不接受占位口令。
- 比较改用 `secrets.compare_digest`（恒定时间），避免按字节试探。
- 未配置时启动日志打 `admin_endpoints_disabled` 警告。

保留了「未配置令牌时 HTTP 401」的分支语义：**401 仍然是「凭据不对」**，
503 表示「这个能力被关闭了」，两者区分开。

### 4. 顺带收敛的三个具体暴露面

- **归档路径穿越**：`/v1/admin/l3/dump` 的 `user_id` 被拼进归档文件名，
  `user_id="../../evil"` 可写到归档根之外。现在文件名经 `safe_filename()` 净化，
  写入前再由 `resolve_within()` 断言路径未逃出归档根（绝对路径 / 盘符 / UNC 一律拒绝）。
- **demo 存储型 XSS**：`demo/index.html` 的 `setStatus()` 用 `innerHTML` 渲染，
  而渲染内容里的实体名、记忆正文摘要、纠正文本都是用户可写数据。配合第 1 条之前
  「无鉴权」，攻击者先写一条带 payload 的记忆，受害者打开 demo 就会执行它。
  改为 `textContent`。
- **impact 路径枚举放大**：`/v1/graph/impact` 枚举所有简单路径且无上限，
  `max_hops=5` + 高度数节点会组合爆炸，而该端点此前无鉴权。新增
  `ERAHERM_GRAPH_MAX_PATHS`（默认 200）并把关系索引提到 BFS 之外
  （原来每条路径都重建一次）。

## 后果

### 正面

- 默认形态（`127.0.0.1` + 无 token）本机可用、零配置，且**不可能**被其它机器访问。
- 要对外提供服务时，必须显式做一次安全决策（配 token 或显式声明不安全），
  不会「不小心」把记忆库挂到公网。
- admin 能力不再有一个全世界都知道的口令。
- 上面三个具体漏洞被关掉，且都有回归测试或可直接验证的纯函数。

### 负面 / 已知限制

- `ERAHERM_HOST=0.0.0.0` 的存量部署升级后会启动失败（见第 2 条的理由，这是有意的）。
- 共享密钥 = 单租户。**多用户隔离仍未解决**：拿到 token 的客户端仍可通过
  自报 `user_id` 访问别人的记忆。真正修好需要「user_id 从认证主体派生」，
  这要求引入用户/凭据模型。
- demo 与 API 同源的问题只是缓解（XSS 修掉了）；生产仍建议
  `ERAHERM_ENABLE_DEMO=false`，不要让 API 进程同时当静态站点。
- 没有速率限制：token 可以被暴力猜（虽然长随机串不现实），也没有针对
  `remember` 的请求体大小上限。

### 后续（未做，按触发条件）

| 触发条件 | 动作 |
|---|---|
| 第二个真人用户 / 要把记忆服务对外提供 | 用户模型：user_id 从认证主体派生（API key → user_id），彻底去掉请求体里的 `user_id`；`memory_id`/`session_id` 取用一律带归属条件 |
| 有公网部署 | 速率限制 + 请求体大小上限（`content` 目前无长度约束） |
| 多租户 | `embeddings` 表加 `tenant_id`，让向量检索**前置**过滤租户（现在是事后过滤，top-k 可能被其它租户占满导致召回为空） |
| 敏感内容要真防泄漏 | `app/sensitive.py` 是中文关键词表，不是可靠边界；要么用本地 embedding，要么在 adapter 层做数据防泄漏（DLP）而不是入口正则 |

## 参考

- 实现：`app/security.py`、`app/api/auth.py`、`app/main.py`、`app/adapters/filesystem_archive.py`
- 测试：`tests/test_security.py`（认证依赖用真实 FastAPI TestClient 覆盖）
- 相关：[ADR 0001](0001-kernel-not-full-agent.md)（内核而非完整 Agent）、
  [SECURITY.md](../../SECURITY.md)
