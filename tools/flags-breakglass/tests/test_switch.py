"""Break-glass switch: admin API path, database fallback and explicit failures."""

from __future__ import annotations

import httpx
import pytest

from flags_breakglass.adapters import UnleashAdminApi
from flags_breakglass.application import plan, switch
from flags_breakglass.domain import BreakGlassError, FlagTarget, Path

TARGET = FlagTarget("trail.recording", "default", "production")


def _api(handler) -> UnleashAdminApi:
    return UnleashAdminApi(httpx.Client(base_url="http://unleash", transport=httpx.MockTransport(handler)))


class FakeDatabase:
    def __init__(self, rows: int = 1) -> None:
        self.rows = rows
        self.state: bool | None = None

    def set_enabled(self, target: FlagTarget, enabled: bool) -> int:
        self.state = enabled
        return self.rows

    def is_enabled(self, target: FlagTarget) -> bool:
        assert self.state is not None
        return self.state


def test_switch_off_through_admin_api_reads_back() -> None:
    state = {"enabled": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/admin/ui-config":
            return httpx.Response(200, json={})
        if request.url.path.endswith("/environments/production/off"):
            assert request.method == "POST"
            state["enabled"] = False
            return httpx.Response(200)
        if request.url.path == "/api/admin/projects/default/features/trail.recording":
            return httpx.Response(200, json={"environments": [{"name": "production", "enabled": state["enabled"]}]})
        return httpx.Response(404)

    outcome = switch(TARGET, False, _api(handler), None)
    assert outcome.path is Path.ADMIN_API and outcome.verified and outcome.enabled is False


def test_falls_back_to_database_when_service_is_down() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    database = FakeDatabase()
    outcome = switch(TARGET, False, _api(handler), database)
    assert outcome.path is Path.DATABASE and database.state is False
    assert "takes effect when the service starts" in outcome.note


def test_service_down_without_database_is_an_explicit_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(BreakGlassError, match="FLAGS_BREAKGLASS_DSN_FILE"):
        switch(TARGET, False, _api(handler), None)


def test_unknown_flag_in_database_is_an_explicit_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(BreakGlassError, match="no row"):
        switch(TARGET, False, _api(handler), FakeDatabase(rows=0))


def test_admin_api_refusal_is_not_hidden_by_the_fallback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/admin/ui-config":
            return httpx.Response(200)
        return httpx.Response(403)

    with pytest.raises(BreakGlassError, match="HTTP 403"):
        switch(TARGET, False, _api(handler), FakeDatabase())


def test_flag_key_must_be_dotted_lowercase() -> None:
    with pytest.raises(BreakGlassError):
        FlagTarget("Trail Recording", "default", "production")


def test_missing_token_file_is_a_configuration_error(monkeypatch, tmp_path) -> None:
    from typer.testing import CliRunner

    from flags_breakglass.cli.main import app

    monkeypatch.setenv("FLAGS_BREAKGLASS_URL", "http://unleash")
    monkeypatch.setenv("FLAGS_BREAKGLASS_TOKEN_FILE", str(tmp_path / "absent"))
    result = CliRunner().invoke(app, ["kill", "trail.recording"])
    assert result.exit_code == 2


def test_database_errors_never_echo_the_dsn() -> None:
    from flags_breakglass.adapters import UnleashDatabase

    database = UnleashDatabase("postgresql://unleash:s3cret-value@unresolvable.invalid:1/unleash?connect_timeout=1")
    with pytest.raises(BreakGlassError) as caught:
        database.set_enabled(TARGET, False)
    assert "s3cret-value" not in str(caught.value) and caught.value.__cause__ is None


def test_rejected_token_is_explicit_and_never_writes_the_database() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    database = FakeDatabase()
    with pytest.raises(BreakGlassError, match="rejected the token"):
        switch(TARGET, False, _api(handler), database)
    assert database.state is None


def test_dry_run_reads_through_the_admin_api_and_writes_nothing() -> None:
    writes: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            writes.append(request.url.path)
        if request.url.path == "/api/admin/ui-config":
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"environments": [{"name": "production", "enabled": True}]})

    outcome = plan(TARGET, False, _api(handler), FakeDatabase())
    assert outcome.path is Path.ADMIN_API and not outcome.verified and "currently on" in outcome.note
    assert writes == []


def test_dry_run_with_service_down_reads_the_database_only() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502)

    class ReadOnlyDatabase(FakeDatabase):
        def set_enabled(self, target: FlagTarget, enabled: bool) -> int:
            raise AssertionError("dry run must not write")

    database = ReadOnlyDatabase()
    database.state = True
    outcome = plan(TARGET, False, _api(handler), database)
    assert outcome.path is Path.DATABASE and "database has it on" in outcome.note


def test_cli_dry_run_prints_the_plan(monkeypatch, tmp_path) -> None:
    from typer.testing import CliRunner

    from flags_breakglass.cli import main

    token = tmp_path / "token"
    token.write_text("user:test\n")
    monkeypatch.setenv("FLAGS_BREAKGLASS_URL", "http://unleash")
    monkeypatch.setenv("FLAGS_BREAKGLASS_TOKEN_FILE", str(token))
    monkeypatch.setattr(
        main,
        "_api",
        lambda settings: _api(
            lambda request: httpx.Response(200, json={"environments": [{"name": "production", "enabled": False}]})
        ),
    )
    result = CliRunner().invoke(main.app, ["kill", "trail.recording", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert '"dry_run": true' in result.stdout and '"verified": false' in result.stdout
