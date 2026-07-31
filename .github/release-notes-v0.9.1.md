## EraHerm-Memory v0.9.1

开源向小版本：召回假阳性/多 pinned 串扰修复 + 贡献入口补齐。

### Highlights
- 零词法重叠时抬高召回门槛（`ERAHERM_RECALL_MIN_SCORE_NO_LEXICAL`）
- pinned 改为分数加权排序，不再无条件置顶
- CJK 词法 bigram；`correct_creates_pinned` 默认 `true`
- 贡献指南补充 Good First Issue 方向

### Install
```bash
git clone https://github.com/yangwenhua212/eraherm-memory.git
cd eraherm-memory
git checkout v0.9.1
python -m pip install -e ".[dev,mcp]"
copy .env.example .env   # Unix: cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### Smoke
```bash
python -m pytest -q
python examples/correct_to_evolve.py
```

完整变更见 [CHANGELOG](https://github.com/yangwenhua212/eraherm-memory/blob/v0.9.1/CHANGELOG.md)。  
想贡献？见 [CONTRIBUTING.md](https://github.com/yangwenhua212/eraherm-memory/blob/v0.9.1/CONTRIBUTING.md) 与 Issues 中的 `good first issue`。
