#!/usr/bin/env python3
"""
One-off: create Keycloak groups + group claim mappers + mlflow-api client for MLflow claims gate.
Requires: KEYCLOAK_ADMIN_PASSWORD, LOCAL_DOMAIN, KEYCLOAK_SIGILCORE_REALM, MLFLOW_ADMIN_USERNAME (Keycloak username to add to the admin group) in environment.
Run from repo root: set -a && source .env && set +a && uv run python scripts/keycloak_mlflow_claims_setup.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def _require(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        print(f"Missing env: {name}", file=sys.stderr)
        sys.exit(1)
    return v


def _http_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    payload: dict | list | None = None,
) -> tuple[int, str]:
    headers: dict[str, str] = {}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def main() -> None:
    local_domain = _require("LOCAL_DOMAIN")
    realm = _require("KEYCLOAK_SIGILCORE_REALM")
    admin_pass = _require("KEYCLOAK_ADMIN_PASSWORD")
    base = f"https://idp.{local_domain}"

    token_url = f"{base}/realms/master/protocol/openid-connect/token"
    form = urllib.parse.urlencode(
        {
            "client_id": "admin-cli",
            "grant_type": "password",
            "username": "admin",
            "password": admin_pass,
        }
    ).encode()
    req = urllib.request.Request(
        token_url,
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode()
    token = json.loads(body)["access_token"]

    def get_json(url: str) -> list | dict:
        st, b = _http_json("GET", url, token=token)
        if st != 200:
            print(f"GET {url} -> {st}\n{b}", file=sys.stderr)
            sys.exit(1)
        return json.loads(b)

    def ensure_group(name: str) -> dict:
        search_url = f"{base}/admin/realms/{realm}/groups?search={urllib.parse.quote(name)}&max=50"
        for g in get_json(search_url):
            if g.get("name") == name:
                print(f"group exists: {name} id={g['id']}")
                return g
        url = f"{base}/admin/realms/{realm}/groups"
        st, b = _http_json("POST", url, token=token, payload={"name": name})
        if st not in (201, 204):
            print(f"create group {name} -> {st}\n{b}", file=sys.stderr)
            sys.exit(1)
        for g in get_json(search_url):
            if g.get("name") == name:
                print(f"created group: {name} id={g['id']}")
                return g
        print(f"group {name} not found after create", file=sys.stderr)
        sys.exit(1)

    def find_user_by_username(username: str) -> dict:
        q = urllib.parse.quote(username)
        url = f"{base}/admin/realms/{realm}/users?username={q}&exact=true"
        users = get_json(url)
        if not users:
            print(f"user not found: {username}", file=sys.stderr)
            sys.exit(1)
        return users[0]

    def find_client_by_client_id(client_id: str) -> dict:
        url = f"{base}/admin/realms/{realm}/clients?clientId={urllib.parse.quote(client_id)}"
        items = get_json(url)
        if not items:
            print(f"client not found: {client_id}", file=sys.stderr)
            sys.exit(1)
        return items[0]

    def ensure_group_membership(user_id: str, group_id: str) -> None:
        url = f"{base}/admin/realms/{realm}/users/{user_id}/groups/{group_id}"
        req = urllib.request.Request(
            url,
            data=b"",
            headers={"Authorization": f"Bearer {token}", "Content-Length": "0"},
            method="PUT",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                st = resp.status
                b = resp.read().decode()
        except urllib.error.HTTPError as exc:
            st = exc.code
            b = exc.read().decode()
        if st in (204, 201, 200):
            print(f"joined group {group_id} for user {user_id}")
            return
        if st == 409:
            print(f"already in group {group_id}")
            return
        print(f"PUT membership -> {st}\n{b}", file=sys.stderr)
        sys.exit(1)

    def ensure_protocol_mapper(client_uuid: str, client_label: str) -> None:
        mappers_url = f"{base}/admin/realms/{realm}/clients/{client_uuid}/protocol-mappers/models"
        mappers = get_json(mappers_url)
        for m in mappers:
            if m.get("name") == "groups-claim" or (
                m.get("protocolMapper") == "oidc-group-membership-mapper" and m.get("name") == "groups"
            ):
                print(f"[{client_label}] group mapper already present: {m.get('name')}")
                return
        payload = {
            "name": "groups-claim",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-group-membership-mapper",
            "config": {
                "full.path": "false",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "claim.name": "groups",
                "userinfo.token.claim": "true",
            },
        }
        st, b = _http_json("POST", mappers_url, token=token, payload=payload)
        if st not in (201, 204):
            print(f"[{client_label}] add mapper -> {st}\n{b}", file=sys.stderr)
            sys.exit(1)
        print(f"[{client_label}] created groups-claim mapper")

    def ensure_audience_mapper(client_uuid: str, client_label: str) -> None:
        mappers_url = f"{base}/admin/realms/{realm}/clients/{client_uuid}/protocol-mappers/models"
        mappers = get_json(mappers_url)
        for m in mappers:
            if m.get("name") == "audience-oauth2-proxy":
                print(f"[{client_label}] audience mapper already present")
                return
        payload = {
            "name": "audience-oauth2-proxy",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper",
            "config": {
                "included.client.audience": "oauth2-proxy",
                "included.custom.audience": "",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "userinfo.token.claim": "false",
            },
        }
        st, b = _http_json("POST", mappers_url, token=token, payload=payload)
        if st not in (201, 204):
            print(f"[{client_label}] audience mapper -> {st}\n{b}", file=sys.stderr)
            sys.exit(1)
        print(f"[{client_label}] created audience-oauth2-proxy mapper")

    g_admin = ensure_group("admin")
    g_mlflow = ensure_group("mlflow-admin")

    user = find_user_by_username(_require("MLFLOW_ADMIN_USERNAME"))
    ensure_group_membership(user["id"], g_admin["id"])

    # mlflow-api confidential client with service account (client_credentials)
    clients_url = f"{base}/admin/realms/{realm}/clients"
    existing = get_json(f"{clients_url}?clientId=mlflow-api")
    if existing:
        c = existing[0]
        print(f"client mlflow-api exists id={c['id']}")
        client_uuid = c["id"]
        # ensure service account + settings
        patch = {
            **c,
            "serviceAccountsEnabled": True,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "implicitFlowEnabled": False,
            "publicClient": False,
        }
        st, b = _http_json("PUT", f"{clients_url}/{client_uuid}", token=token, payload=patch)
        if st not in (200, 204):
            print(f"patch mlflow-api -> {st}\n{b}", file=sys.stderr)
            sys.exit(1)
        print("updated mlflow-api client (service account enabled)")
    else:
        payload = {
            "clientId": "mlflow-api",
            "name": "mlflow-api",
            "enabled": True,
            "protocol": "openid-connect",
            "publicClient": False,
            "bearerOnly": False,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": True,
            "implicitFlowEnabled": False,
            "frontchannelLogout": False,
            "redirectUris": [],
            "webOrigins": [],
            "attributes": {},
        }
        st, b = _http_json("POST", clients_url, token=token, payload=payload)
        if st not in (201, 204):
            print(f"create mlflow-api -> {st}\n{b}", file=sys.stderr)
            sys.exit(1)
        client_uuid = find_client_by_client_id("mlflow-api")["id"]
        print(f"created mlflow-api client uuid={client_uuid}")

    # Fetch client secret (for local .env / secrets)
    secret_url = f"{base}/admin/realms/{realm}/clients/{client_uuid}/client-secret"
    st, b = _http_json("GET", secret_url, token=token)
    if st != 200:
        print(f"get secret -> {st}\n{b}", file=sys.stderr)
        sys.exit(1)
    secret_val = json.loads(b)["value"]
    secrets_dir = os.path.join(os.getcwd(), "secrets", "keycloak")
    os.makedirs(secrets_dir, exist_ok=True)
    path = os.path.join(secrets_dir, "mlflow_api_client_secret")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(secret_val + "\n")
    print(f"wrote {path}")

    # Service account user
    sa_url = f"{base}/admin/realms/{realm}/clients/{client_uuid}/service-account-user"
    st, b = _http_json("GET", sa_url, token=token)
    if st != 200:
        print(f"service-account-user -> {st}\n{b}", file=sys.stderr)
        sys.exit(1)
    sa_user = json.loads(b)
    ensure_group_membership(sa_user["id"], g_mlflow["id"])

    oauth2 = find_client_by_client_id("oauth2-proxy")
    ensure_protocol_mapper(oauth2["id"], "oauth2-proxy")
    ensure_protocol_mapper(client_uuid, "mlflow-api")
    ensure_audience_mapper(client_uuid, "mlflow-api")

    print("done.")


if __name__ == "__main__":
    main()
