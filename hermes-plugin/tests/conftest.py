"""让 hermes-plugin 测试在本地仓库也能跑（Hermes 仓库布局兼容）。

正式环境：测试按 Hermes 仓库布局 plugins/memory/eraherm/ 放置（见 README 验证节）。
本地：通过 importlib 把 hermes-plugin/__init__.py 注册为 plugins.memory.eraherm，
使 `from plugins.memory.eraherm import ...` 在两种布局下都可用。
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

if not sys.modules.get("plugins.memory.eraherm"):
    # stub Hermes ABC（本地测试不依赖 Hermes 仓库）
    if not sys.modules.get("agent"):
        _agent = types.ModuleType("agent")
        _mp = types.ModuleType("agent.memory_provider")

        class MemoryProvider:  # type: ignore[no-redef]
            def initialize(self, *a, **k):
                raise NotImplementedError

            def shutdown(self, *a, **k):
                raise NotImplementedError

        _mp.MemoryProvider = MemoryProvider
        _agent.memory_provider = _mp  # type: ignore[attr-defined]
        sys.modules["agent"] = _agent
        sys.modules["agent.memory_provider"] = _mp

    plugin_init = Path(__file__).resolve().parent.parent / "__init__.py"

    plugins = types.ModuleType("plugins")  # type: ignore[attr-defined]
    memory = types.ModuleType("plugins.memory")
    plugins.memory = memory  # type: ignore[attr-defined]
    sys.modules["plugins"] = plugins
    sys.modules["plugins.memory"] = memory

    assert plugin_init.is_file()
    spec = importlib.util.spec_from_file_location("plugins.memory.eraherm", plugin_init)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plugins.memory.eraherm"] = mod
    spec.loader.exec_module(mod)
