# MCP 接入指南

> 把 EraHerm-Memory 内核挂到 Cursor / Claude Desktop：记忆变成标准 **MCP Tools**。

## 工具一览

| Tool | 对应能力 |
|------|----------|
| `remember` | 写入记忆（含 `alerts`） |
| `recall` | 语义召回 + `recommendations` |
| `impact` | 图谱影响面 |
| `consolidate` | 手动触发记忆整理 |
| `health` | 健康检查 |

## 安装

```bash
python -m pip install -e ".[mcp]"
```

## 启动（stdio）

```bash
python -m app.mcp_server
```

Host（Claude Desktop / Cursor）会以子进程方式拉起该命令，无需先开 uvicorn。

## 配置文件

仓库根目录 `mcp.json` 示例：

```json
{
  "mcpServers": {
    "eraherm-memory": {
      "command": "python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "D:/bk/agent",
      "env": {
        "ERAHERM_DATABASE_URL": "sqlite:///./storage/eraherm.db",
        "ERAHERM_EMBEDDING_BACKEND": "hashing",
        "ERAHERM_JSON_LOGS": "false"
      }
    }
  }
}
```

本地 Demo 可用 `hashing`。**对外演示语义召回或挂 Hermes 时**，把 env 改成真实 embedding，例如：

```json
"env": {
  "ERAHERM_DATABASE_URL": "sqlite:///./storage/eraherm.db",
  "ERAHERM_EMBEDDING_BACKEND": "openai",
  "ERAHERM_EMBEDDING_API_KEY": "sk-...",
  "ERAHERM_EMBEDDING_MODEL": "text-embedding-3-small",
  "ERAHERM_EMBEDDING_DIM": "1536",
  "ERAHERM_JSON_LOGS": "false"
}
```

禁止在生产路径长期保留 `ERAHERM_EMBEDDING_BACKEND=hashing`（详见 README「生产 Embedding」）。

### Claude Desktop

把上述 `mcpServers` 合并进：

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

重启 Claude Desktop 后，对话里应出现 EraHerm tools。

### Cursor

在 Cursor MCP 设置中添加同等配置，或把 `mcp.json` 内容同步到 Cursor 的 MCP servers。

## 演示话术

1. 先让助手调用 `remember`：`项目核心依赖是 FastAPI 与 PostgreSQL`（`user_id=demo`）
2. 新开话题问：「我之前项目里那个核心依赖是什么？」
3. 助手应调用 `recall`，再根据返回内容回答。

## 与 HTTP API 的关系

| 模式 | 用途 |
|------|------|
| HTTP `uvicorn` | Agent SDK / Demo / 评测 |
| MCP stdio | IDE / Desktop 一键挂载 |

二者共享同一套领域服务与 SQLite；改 `ERAHERM_DATABASE_URL` 即可指向同一库。
