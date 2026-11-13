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
        return self._client.get("/health").status_code == 200

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
    """Direct access to Unleash's own tables, for when every Unleash replica is down but the database is up."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def set_enabled(self, target: FlagTarget, enabled: bool) -> int:
        with psycopg.connect(self._dsn, connect_timeout=10) as connection:
            cursor = connection.execute(
                "UPDATE feature_environments SET enabled = %s WHERE feature_name = %s AND environment = %s",
                (enabled, target.key, target.environment),
            )
            return cursor.rowcount

    def is_enabled(self, target: FlagTarget) -> bool:
        with psycopg.connect(self._dsn, connect_timeout=10) as connection:
            row = connection.execute(
                "SELECT enabled FROM feature_environments WHERE feature_name = %s AND environment = %s",
                (target.key, target.environment),
            ).fetchone()
        if row is None:
            raise BreakGlassError(f"database has no row for {target.key} in {target.environment}")
        return bool(row[0])
