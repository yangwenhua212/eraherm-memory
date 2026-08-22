"""Tests for plugins/memory/eraherm/__init__.py — EraHerm MemoryProvider.

Unit-level: fake HTTP layer, no live service required.
Mirrors the style of tests/plugins/memory/test_openviking_provider.py.
"""

import json
import unittest
from unittest import mock

from plugins.memory.eraherm import EraHermMemoryProvider


class FakeResponse:
    def __init__(self, data, status=200):
        self._data = data
        self.status = status

    def read(self):
        return json.dumps(self._data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestEraHermIdentity(unittest.TestCase):
    def test_name_is_eraherm(self):
        assert EraHermMemoryProvider().name == "eraherm"

    def test_user_id_stable_after_initialize(self):
        """user_id must NOT drift with gateway user_id (HERMES_INTEGRATION §3).

        The module reads ERAHERM_MEMORY_USER once at import time (like Hermes
        startup). initialize() must keep that value regardless of the
        platform user_id passed in kwargs.
        """
        import plugins.memory.eraherm as mod
        p = EraHermMemoryProvider()
        p.initialize("sess-1", user_id="gateway-user-123")
        assert p._user_id == mod._ERAHERM_USER  # 稳定值，不随网关用户漂移
        assert p._user_id != "gateway-user-123"


class TestEraHermCircuitBreaker(unittest.TestCase):
    def _provider_with_failures(self, n, breaker_open_until=None):
        p = EraHermMemoryProvider()
        p._consecutive_failures = n
        if breaker_open_until is not None:
            p._breaker_open_until = breaker_open_until
        return p

    def test_breaker_opens_after_threshold(self):
        p = self._provider_with_failures(5, breaker_open_until=9999999999.0)
        assert p._is_breaker_open() is True

    def test_breaker_closed_below_threshold(self):
        p = self._provider_with_failures(3, breaker_open_until=9999999999.0)
        assert p._is_breaker_open() is False

    def test_breaker_recovers_after_cooldown(self):
        p = self._provider_with_failures(5)
        p._breaker_open_until = 0  # cooldown expired
        assert p._is_breaker_open() is False


class TestEraHermToolSchemas(unittest.TestCase):
    def setUp(self):
        self.p = EraHermMemoryProvider()

    def test_schemas_expose_remember_and_recall(self):
        names = [s["name"] for s in self.p.get_tool_schemas()]
        assert "eraherm_remember" in names
        assert "eraherm_recall" in names

    def test_unknown_tool_returns_error(self):
        out = json.loads(self.p.handle_tool_call("nope", {}))
        assert out["ok"] is False


class TestEraHermRecallErrorPropagation(unittest.TestCase):
    def test_unreachable_service_reports_error_not_empty_success(self):
        """Service down must surface as ok:false, not a misleading empty recall."""
        p = EraHermMemoryProvider()
        with mock.patch("urllib.request.urlopen", side_effect=Exception("conn refused")):
            items = p._recall("hello")
            assert items == []
            assert p._last_error  # error recorded
            out = json.loads(p.handle_tool_call("eraherm_recall", {"query": "hello"}))
            assert out["ok"] is False
            assert "unreachable" in out["error"]


class TestEraHermPrefetch(unittest.TestCase):
    def test_skip_trivial_query(self):
        p = EraHermMemoryProvider()
        assert p.prefetch("") == ""
        assert p.prefetch("嗯") == ""

    def test_prefetch_injects_items(self):
        p = EraHermMemoryProvider()
        with mock.patch.object(p, "_recall", return_value=["[0.8] 用户喜欢喝冰美式", "[0.6] 数据库用 PostgreSQL"]):
            block = p.prefetch("用户偏好")
            assert "用户喜欢喝冰美式" in block
            assert "自动注入" in block

    def test_prefetch_empty_recall_returns_empty(self):
        p = EraHermMemoryProvider()
        with mock.patch.object(p, "_recall", return_value=[]):
            assert p.prefetch("随便") == ""


class TestEraHermConfigSchema(unittest.TestCase):
    def test_config_schema_env_vars(self):
        p = EraHermMemoryProvider()
        fields = {f["key"]: f for f in p.get_config_schema()}
        assert set(fields) == {"base_url", "user_id", "top_k", "min_score", "admin_token"}
        assert fields["base_url"]["env_var"] == "ERAHERM_URL"
        assert fields["user_id"]["env_var"] == "ERAHERM_MEMORY_USER"
        assert fields["admin_token"]["secret"] is True


class TestEraHermSessionEnd(unittest.TestCase):
    def test_no_admin_token_skips_consolidate(self):
        p = EraHermMemoryProvider()
        with mock.patch.dict("os.environ", {"ERAHERM_ADMIN_TOKEN": ""}, clear=False):
            p.on_session_end([])  # should not raise


class TestEraHermMemoryWriteMirror(unittest.TestCase):
    def test_remove_action_ignored(self):
        p = EraHermMemoryProvider()
        with mock.patch("urllib.request.urlopen") as urlopen:
            p.on_memory_write("remove", "memory", "旧条目")
            urlopen.assert_not_called()

    def test_add_action_mirrors_content(self):
        p = EraHermMemoryProvider()
        p._user_id = "test-user"
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value = FakeResponse({"id": "mem_123"})
            p.on_memory_write("add", "memory", "新事实", metadata={"tool_name": "memory_tool"})
            req = urlopen.call_args[0][0]
            body = json.loads(req.data.decode())
            assert "mirrored" in body["content"]
            assert "新事实" in body["content"]
            assert body["user_id"] == "test-user"


if __name__ == "__main__":
    unittest.main()
