## EraHerm-Memory v0.9.0

自用向增强：真实 embedding、召回门禁、全量重嵌、Hermes 内置 Tools。  
卖点不变：**纠正即进化**。

### 你该做什么（服务器）

1. `git pull` / `git checkout v0.9.0`
2. `pip install -e '.[fastembed]'`
3. `.env`：`fastembed` + `DIM=512` + `RECALL_MIN_SCORE=0.25`
4. `eraherm-reembed --orphan-user-id <稳定user_id>`
5. 注册 `HermesMemoryTools`（停 curl）
6. 本地验：`python examples/correct_to_evolve.py`

检查表见 [HERMES_INTEGRATION.md §8](https://github.com/yangwenhua212/eraherm-memory/blob/v0.9.0/docs/HERMES_INTEGRATION.md)。

完整变更见 [CHANGELOG.md](https://github.com/yangwenhua212/eraherm-memory/blob/v0.9.0/CHANGELOG.md)。
