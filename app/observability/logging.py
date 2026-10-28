# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import logging
import sys
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": self.formatTime(record, self.datefmt),
        }
        for key in (
            "request_id",
            "path",
            "method",
            "status_code",
            "duration_ms",
            "op",
            # 诊断上下文（否则 extra 里的关键信息会被静默丢掉）
            "detail",
            "reason",
            "user_id",
            "memory_type",
            "layer",
            "memory_id",
        ):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_installed_handler: logging.Handler | None = None


def setup_logging(*, level: str = "INFO", json_logs: bool = True) -> None:
    """安装 EraHerm 的日志处理器（**幂等，且不破坏宿主的日志配置**）。

    以前这里第一行是 ``root.handlers.clear()``：一个**可嵌入**的记忆内核不该把宿主
    进程 root 上的 handlers 全清掉 —— 那会静默禁用宿主自己的日志，也会清掉 pytest
    的 caplog handler。

    这条缺陷只在「同一进程里先有别的日志配置、之后再构建 container」时暴露：
    全量跑测试时前面的用例触发了 ``build_container()``（它会调 setup_logging），
    后面用例的 caplog 就再也收不到任何记录（``tests/test_proclock.py`` 的
    日志断言就是这么挂的）。单跑该文件则正常 —— 典型的测试隔离问题。

    现在只移除**自己装过的**那个 handler，root 上的其它 handler 原样保留。
    """
    global _installed_handler
    root = logging.getLogger()
    if _installed_handler is not None:
        try:
            root.removeHandler(_installed_handler)
            _installed_handler.close()
        except Exception:  # noqa: BLE001
            pass
        _installed_handler = None
    handler = logging.StreamHandler(sys.stdout)
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    # 标记成「我们装的」，便于下次替换，也让排查时一眼看出是谁加的
    handler._eraherm_owned = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level.upper())
    _installed_handler = handler


logger = logging.getLogger("eraherm")
