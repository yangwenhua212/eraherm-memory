# EraHerm Memory Provider — Hermes 官方集成

EraHerm-Memory 作为 **Hermes 的长期记忆层**（Memory Provider）接入 Hermes 原生记忆体系。

> 定位：不是「Cursor 插件」，不是又一个 RAG 工具——是 Hermes 操作系统的**原生内存**。
> 对应仓库文档：[HERMES_INTEGRATION.md](../docs/HERMES_INTEGRATION.md) §0、[ROADMAP.md](../docs/ROADMAP.md) 战略定位。

## 安装

### 方式 A：用户级插件（自用/试用，最快）

```bash
mkdir -p ~/.hermes/plugins/eraherm
cp __init__.py ~/.hermes/plugins/eraherm/
cp plugin.yaml ~/.hermes/plugins/eraherm/

# 配置
hermes config set memory.provider eraherm
```

写入 `~/.hermes/.env`：

```env
ERAHERM_URL=http://127.0.0.1:8000
ERAHERM_MEMORY_USER=xiaoxian
ERAHERM_MEMORY_TOP_K=6
ERAHERM_MEMORY_MIN_SCORE=0.25
# 可选：会话结束自动整理压缩
ERAHERM_ADMIN_TOKEN=your-admin-token
```

重启 gateway / CLI 后生效。

### 方式 B：随 Hermes 官方分发（提交 PR 后）

目录 `plugins/memory/eraherm/`，随 hermes-agent 仓库发布，用户 `hermes memory setup eraherm` 引导配置。

## 能力

| 生命周期钩子 | 作用 |
|--------------|------|
| `prefetch()` | 每轮自动召回相关长期记忆注入上下文（后台预热，不阻塞） |
| `sync_turn()` | 每轮后台把「值得记住」的对话沉淀为记忆（启发式防噪声） |
| `on_session_end()` | 会话结束时触发 EraHerm consolidate 整理压缩（需 admin token） |
| `on_memory_write()` | 内置 MEMORY.md / user profile 写入时镜像到 EraHerm |
| `on_pre_compress()` | 上下文压缩前把即将丢弃的消息提炼为记忆 |
| `eraherm_remember` / `eraherm_recall` | 原生工具（LLM 可直接调用） |

**断路器**：EraHerm 服务连续失败 5 次后暂停 120s，避免服务挂掉时疯狂重试。

## 架构

```
Hermes Agent Core（调度者）
   │
   ├── MemoryManager ──► eraherm provider（本插件）
   │        ├── prefetch：每轮注入相关记忆
   │        ├── sync_turn：每轮沉淀对话
   │        ├── on_session_end：整理压缩
   │        └── on_memory_write：内置记忆镜像
   │
   └── MCP eraherm-memory（工具面，可选并存）
                    │
                    ▼
         EraHerm-Memory Kernel（localhost:8000）
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
    事实记忆     项目记忆     用户记忆
```

## 开发

- 零 pip 依赖（仅标准库 + urllib）
- 实现 `agent.memory_provider.MemoryProvider` ABC
- 入口 `register(ctx)`，加载器调用 `ctx.register_memory_provider(...)`
- 配置全走 env vars（`get_config_schema` 已标 `env_var`）

## 验证

```bash
cd ~/.hermes/hermes-agent
venv/bin/python -c "
from plugins.memory import discover_memory_providers, load_memory_provider
print([n for n,_,_ in discover_memory_providers()])   # 应含 eraherm
p = load_memory_provider('eraherm'); print(p.is_available())
"
```

运行时日志：`grep -i eraherm ~/.hermes/logs/agent.log | tail`
