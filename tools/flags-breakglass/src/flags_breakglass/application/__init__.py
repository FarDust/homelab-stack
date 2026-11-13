"""Use cases: switch a flag through the admin API, or through the database when the service is down."""

from __future__ import annotations

from typing import Protocol

from flags_breakglass.domain import BreakGlassError, FlagTarget, Path, SwitchOutcome


class AdminApi(Protocol):
    def health(self) -> bool: ...
    def set_enabled(self, target: FlagTarget, enabled: bool) -> None: ...
    def is_enabled(self, target: FlagTarget) -> bool: ...
    def export(self, project: str, environment: str) -> dict[str, object]: ...


class FlagDatabase(Protocol):
    def set_enabled(self, target: FlagTarget, enabled: bool) -> int: ...
    def is_enabled(self, target: FlagTarget) -> bool: ...


def plan(target: FlagTarget, enabled: bool, api: AdminApi, database: FlagDatabase | None) -> SwitchOutcome:
    """Dry run of :func:`switch`: choose the path and read the current state through it, without writing.

    ``verified`` is False because nothing was changed; the note states the current value and what a real run does.
    """
    want = "on" if enabled else "off"
    api_error: Exception | None = None
    try:
        if api.health():
            state = "on" if api.is_enabled(target) else "off"
            return SwitchOutcome(target, enabled, Path.ADMIN_API, False, f"dry run: currently {state}; would switch {want}")
        api_error = BreakGlassError("admin API health check did not answer 200")
    except BreakGlassError:
        raise
    except Exception as error:  # same fallback rule as switch(); keep the cause
        api_error = error
    if database is None:
        raise BreakGlassError(
            f"admin API unavailable ({api_error!r}) and no database DSN configured; set FLAGS_BREAKGLASS_DSN_FILE"
        ) from api_error
    state = "on" if database.is_enabled(target) else "off"
    return SwitchOutcome(
        target, enabled, Path.DATABASE, False, f"dry run: admin API unavailable, database has it {state}; would switch {want}"
    )


def switch(target: FlagTarget, enabled: bool, api: AdminApi, database: FlagDatabase | None) -> SwitchOutcome:
    """Switch a flag through the admin API; fall back to the database only when the API is unreachable.

    The outcome is verified by reading the state back through the same path. A database change reaches clients
    only after the service starts again, which the outcome says explicitly.
    """
    api_error: Exception | None = None
    try:
        if not api.health():
            api_error = BreakGlassError("admin API health check did not answer 200")
        else:
            api.set_enabled(target, enabled)
            if api.is_enabled(target) != enabled:
                raise BreakGlassError(f"admin API accepted the change of {target.key} but reads it back unchanged")
            return SwitchOutcome(target, enabled, Path.ADMIN_API, True, "live: SDKs and clients pick it up on their next refresh")
    except BreakGlassError:
        raise
    except Exception as error:  # the API being down is the expected reason to fall back; keep the cause
        api_error = error
    if database is None:
        raise BreakGlassError(
            f"admin API unavailable ({api_error!r}) and no database DSN configured; set FLAGS_BREAKGLASS_DSN_FILE"
        ) from api_error
    rows = database.set_enabled(target, enabled)
    if rows != 1:
        raise BreakGlassError(
            f"database has no row for {target.key} in {target.environment} (updated {rows}); check the key and environment"
        )
    if database.is_enabled(target) != enabled:
        raise BreakGlassError(f"database update of {target.key} did not persist")
    return SwitchOutcome(
        target,
        enabled,
        Path.DATABASE,
        True,
        "stored in the database: takes effect when the service starts; clients keep their cached value until then",
    )
