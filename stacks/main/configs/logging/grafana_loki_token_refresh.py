#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.parse
import urllib.request


def require_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if not value:
        print(f"Missing required env var: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def read_token_from_file(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except FileNotFoundError:
        return None


def request_json(
    url: str,
    method: str = "GET",
    data: dict | None = None,
    headers: dict | None = None,
    timeout: int = 15,
) -> dict:
    payload = None
    request_headers = headers or {}
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
        request_headers = {
            "Content-Type": "application/json",
            **request_headers,
        }
    req = urllib.request.Request(url, data=payload, headers=request_headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_access_token(token_url: str, client_id: str, client_secret: str, timeout: int) -> tuple[str, int]:
    form = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        token_url,
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    token = payload.get("access_token")
    expires_in = int(payload.get("expires_in") or 300)
    if not token:
        raise RuntimeError("Token endpoint did not return access_token")
    return token, expires_in


def build_datasource_payload(datasource: dict, bearer: str) -> dict:
    json_data = datasource.get("jsonData") or {}
    json_data["httpHeaderName1"] = "Authorization"
    return {
        "id": datasource.get("id"),
        "uid": datasource.get("uid"),
        "orgId": datasource.get("orgId"),
        "name": datasource.get("name"),
        "type": datasource.get("type"),
        "access": datasource.get("access"),
        "url": datasource.get("url"),
        "basicAuth": datasource.get("basicAuth", False),
        "isDefault": datasource.get("isDefault", False),
        "jsonData": json_data,
        "secureJsonData": {"httpHeaderValue1": bearer},
    }


def main() -> None:
    grafana_url = require_env("GRAFANA_URL")
    datasource_uid = require_env("GRAFANA_DATASOURCE_UID")
    token_url = require_env("KEYCLOAK_TOKEN_URL")
    client_id = require_env("KEYCLOAK_CLIENT_ID")
    client_secret = require_env("KEYCLOAK_CLIENT_SECRET")
    timeout = int(os.getenv("HTTP_TIMEOUT_SECONDS", "15"))

    api_token = os.getenv("GRAFANA_API_TOKEN")
    api_token_file = os.getenv("GRAFANA_API_TOKEN_FILE")
    if not api_token and api_token_file:
        api_token = read_token_from_file(api_token_file)
    if not api_token:
        print("Missing Grafana API token (GRAFANA_API_TOKEN or GRAFANA_API_TOKEN_FILE).", file=sys.stderr)
        sys.exit(1)

    safety_seconds = int(os.getenv("REFRESH_SAFETY_SECONDS", "60"))
    min_refresh = int(os.getenv("MIN_REFRESH_SECONDS", "60"))
    auth_header = {"Authorization": f"Bearer {api_token}"}

    print("Starting Grafana Loki token refresher.", flush=True)
    while True:
        try:
            access_token, expires_in = fetch_access_token(token_url, client_id, client_secret, timeout)
            bearer = f"Bearer {access_token}"
            datasource = request_json(
                f"{grafana_url}/api/datasources/uid/{datasource_uid}",
                headers=auth_header,
                timeout=timeout,
            )
            payload = build_datasource_payload(datasource, bearer)
            request_json(
                f"{grafana_url}/api/datasources/uid/{datasource_uid}",
                method="PUT",
                data=payload,
                headers=auth_header,
                timeout=timeout,
            )
            sleep_for = max(min_refresh, expires_in - safety_seconds)
            print(f"Refreshed Loki datasource token; next refresh in {sleep_for}s.", flush=True)
            time.sleep(sleep_for)
        except Exception as exc:
            print(f"Token refresh failed: {exc}. Retrying in 30s.", file=sys.stderr, flush=True)
            time.sleep(30)


if __name__ == "__main__":
    main()
