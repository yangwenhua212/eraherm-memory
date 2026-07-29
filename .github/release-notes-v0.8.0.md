## EraHerm-Memory v0.8.0

可嵌入 Agent 的记忆内核：分层记忆 · 知识图谱 · 反馈进化 · MCP · 记忆整理。

### Highlights
- **MCP Server**：`remember` / `recall` / `impact` / `consolidate` / `health`
- **Consolidation**：重要性重排、摘要压缩、冲突淘汰
- **Hermes 集成**：`docs/HERMES_INTEGRATION.md` + `examples/hermes_memory_adapter.py`
- **主动预警 / 推荐**：`alerts[]`、`recommendations[]`
- **许可**：AGPL-3.0-only；闭源商用见 `COMMERCIAL.md`

### Notes
- 开发默认 `hashing` embedding；**生产 / Hermes 请改用 openai 或兼容端点**
- Demo：http://127.0.0.1:8000/demo/ （需本地启动）

### Install
```bash
git clone https://github.com/yangwenhua212/eraherm-memory.git
cd eraherm-memory
git checkout v0.8.0
python -m pip install -e ".[dev,mcp,scheduler]"
```

完整变更见 [CHANGELOG.md](https://github.com/yangwenhua212/eraherm-memory/blob/v0.8.0/CHANGELOG.md)。
