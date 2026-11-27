"""vault-sync stops the cycle when the model backend refuses every request."""
import importlib.util
import sys
import types
from pathlib import Path

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "stacks/main/configs/maintenance/vault_sync.py"


@pytest.fixture
def module(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    for index in range(5):
        (vault / f"note{index}.md").write_text("x" * 100, encoding="utf-8")
    (tmp_path / "key").write_text("k", encoding="utf-8")
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("LITELLM_API_KEY_FILE", str(tmp_path / "key"))
    monkeypatch.setitem(sys.modules, "neo4j", types.SimpleNamespace(GraphDatabase=object))
    spec = importlib.util.spec_from_file_location("vault_sync_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vault_sync_under_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "MANIFEST_PATH", tmp_path / "manifest.tsv", raising=False)
    return mod


def _post_with(status, calls):
    def post(url, **kwargs):
        calls.append(url)
        return httpx.Response(status, json={"error": "x"}, request=httpx.Request("POST", url))

    return post


@pytest.mark.parametrize("status", [401, 402, 403, 429])
def test_backend_refusal_stops_the_cycle_after_one_call(module, monkeypatch, status):
    calls = []
    monkeypatch.setattr(module.httpx, "post", _post_with(status, calls))
    module.sync_once(object())
    assert len(calls) == 1


def test_other_http_errors_still_skip_only_that_file(module, monkeypatch):
    calls = []
    monkeypatch.setattr(module.httpx, "post", _post_with(500, calls))
    module.sync_once(object())
    assert len(calls) == 5
