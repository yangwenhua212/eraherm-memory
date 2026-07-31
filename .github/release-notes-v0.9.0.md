## EraHerm-Memory v0.9.0

真实 embedding、召回门禁、全量重嵌、Hermes 内置 Tools、纠正闭环自测脚本。

> 跟踪主干请优先使用更新的 **[v0.9.1](https://github.com/yangwenhua212/eraherm-memory/releases/tag/v0.9.1)**（假阳性/多 pinned 修复 + 贡献模板）。

### Install
```bash
git checkout v0.9.0
python -m pip install -e ".[dev,mcp,fastembed]"
cp .env.example .env
```

### Smoke
```bash
python examples/correct_to_evolve.py
```

完整变更见 [CHANGELOG](https://github.com/yangwenhua212/eraherm-memory/blob/v0.9.0/CHANGELOG.md)。
