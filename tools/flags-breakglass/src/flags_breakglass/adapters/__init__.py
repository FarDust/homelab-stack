"""Concrete adapters: the Unleash admin API over HTTP and the Unleash database over psycopg."""

from __future__ import annotations

import httpx
import psycopg

from flags_breakglass.domain import BreakGlassError, FlagTarget


class UnleashAdminApi:
    """Unleash admin API with an admin API token (never logged)."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def _feature(self, target: FlagTarget) -> str:
        return f"/api/admin/projects/{target.project}/features/{target.key}"

    def health(self) -> bool:
        """True when a replica answers with the token accepted; False when no replica answers (fall back).

        A 401 or 403 means the service is up and the token is wrong: that is raised, never a reason to write to the
        database behind a running service, which would not see the change until it restarts.
        """
        # A token-authenticated admin endpoint: proves the replica, its routing and the token in one call.
        status = self._client.get("/api/admin/ui-config").status_code
        if status in (401, 403):
            raise BreakGlassError(
                f"admin API rejected the token (HTTP {status}); renew the admin PAT, the service itself is up"
            )
        return status == 200

    def set_enabled(self, target: FlagTarget, enabled: bool) -> None:
        state = "on" if enabled else "off"
        response = self._client.post(f"{self._feature(target)}/environments/{target.environment}/{state}")
        if response.status_code not in (200, 202):
            raise BreakGlassError(f"admin API refused switching {target.key} {state}: HTTP {response.status_code}")

    def is_enabled(self, target: FlagTarget) -> bool:
        response = self._client.get(self._feature(target))
        if response.status_code != 200:
            raise BreakGlassError(f"admin API cannot read {target.key}: HTTP {response.status_code}")
        environments = response.json()["environments"]
        for environment in environments:
            if environment["name"] == target.environment:
                return bool(environment["enabled"])
        raise BreakGlassError(f"{target.key} has no environment {target.environment}")

    def export(self, project: str, environment: str) -> dict[str, object]:
        listing = self._client.get(f"/api/admin/projects/{project}/features")
        if listing.status_code != 200:
            raise BreakGlassError(f"admin API cannot list features: HTTP {listing.status_code}")
        names = [feature["name"] for feature in listing.json()["features"]]
        response = self._client.post(
            "/api/admin/features-batch/export", json={"environment": environment, "features": names}
        )
        if response.status_code != 200:
            raise BreakGlassError(f"admin API export failed: HTTP {response.status_code}")
        return response.json()


class UnleashDatabase:
    """Direct access to Unleash's own tables, for when every Unleash replica is down but the database is up.

    psycopg error texts can echo the DSN (password included), so failures surface only the error class.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    @staticmethod
    def _failure(operation: str, error: psycopg.Error) -> BreakGlassError:
        return BreakGlassError(f"database {operation} failed ({type(error).__name__}); check the DSN file and the route to PostgreSQL")

    def set_enabled(self, target: FlagTarget, enabled: bool) -> int:
        try:
            with psycopg.connect(self._dsn, connect_timeout=10) as connection:
                cursor = connection.execute(
                    "UPDATE feature_environments SET enabled = %s WHERE feature_name = %s AND environment = %s",
                    (enabled, target.key, target.environment),
                )
                return cursor.rowcount
        except psycopg.Error as error:
            raise self._failure("update", error) from None

    def is_enabled(self, target: FlagTarget) -> bool:
        try:
            with psycopg.connect(self._dsn, connect_timeout=10) as connection:
                row = connection.execute(
                    "SELECT enabled FROM feature_environments WHERE feature_name = %s AND environment = %s",
                    (target.key, target.environment),
                ).fetchone()
        except psycopg.Error as error:
            raise self._failure("read", error) from None
        if row is None:
            raise BreakGlassError(f"database has no row for {target.key} in {target.environment}")
        return bool(row[0])
