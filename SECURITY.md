# Security Policy

## 支持的版本

| 版本 | 支持 |
|------|------|
| 0.10.x | ✅ 当前 |
| < 0.10 | 有限（`0.x` 可能含破坏性变更） |

## 上报漏洞

请通过私有渠道联系维护者（GitHub Security Advisory / 私信），**不要**在公开 Issue 中披露可复现攻击细节。

请包含：影响版本、复现步骤、预期与实际行为、是否已在公网暴露。

## 已知信任边界（请务必阅读）

EraHerm-Memory 面向 **本地或受控部署**。0.10.2 起默认配置已经收敛为安全形态，
但下面这些边界仍然是**设计取舍**，不是漏洞：

- **默认只绑定 `127.0.0.1`**，本机可用、零配置。要对外提供服务必须二选一：
  设置 `ERAHERM_API_TOKEN`（此后 `/v1/*` 除 `/v1/health` 外都要求
  `X-API-Token` / `Authorization: Bearer`），或显式承认风险
  `ERAHERM_ALLOW_INSECURE_PUBLIC=true`。**没有 token 却绑定非回环地址时，进程会拒绝启动。**
- **`ERAHERM_API_TOKEN` 是单租户共享密钥。** 它认证「谁可以访问这个实例」，
  **不**认证「你可以访问哪个 `user_id`」——`user_id` 仍由请求体自报。
  多用户隔离尚未实现（见 [ADR 0012](docs/adr/0012-api-auth-and-exposure-guard.md) 的「后续」）。
- **`ERAHERM_ADMIN_TOKEN` 未配置时 `/v1/admin/*` 一律 503**（fail-closed）。
  不再有可猜的默认口令；`ERAHERM_ADMIN_TOKEN` 保护的是全库导出（l3 dump）、
  全库删改（consolidate）与用户枚举（watchdog）。
- **敏感内容防护不是可靠的防泄漏边界**：`app/sensitive.py` 是一份中文关键词表，
  且只作用于 LLM 抽取/反射。`openai` embedding 路径会把记忆正文原样发给外部 API，
  也不经过它。真敏感的内容请用本地 embedding（`fastembed`）。
- 启用 OpenAI 兼容后端时，密钥只应来自环境变量，勿写入仓库或 L2 内容。
- 没有速率限制，`content` 也没有长度上限；对公网暴露前请在前置网关补齐。
- Demo 前端与 API 同源；生产建议 `ERAHERM_ENABLE_DEMO=false`。

将服务暴露到公网而不加鉴权 / TLS，仍视为错误配置，而非功能预期。
