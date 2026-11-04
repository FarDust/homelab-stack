#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

set -a
. ./.env
set +a

: "${KEYCLOAK_SIGILCORE_REALM:?KEYCLOAK_SIGILCORE_REALM is required}"
: "${SIGILCORE_LOKI_API_CLIENT_ID:?SIGILCORE_LOKI_API_CLIENT_ID is required}"
: "${SIGILCORE_LOKI_API_CLIENT_SECRET:?SIGILCORE_LOKI_API_CLIENT_SECRET is required}"
: "${LOCAL_DOMAIN:?LOCAL_DOMAIN is required}"
: "${MCP_ADMIN_GRAFANA_API_KEY:?MCP_ADMIN_GRAFANA_API_KEY is required}"

grafana_url="${GRAFANA_URL:-http://grafana:3000}"
datasource_uid="${GRAFANA_LOKI_DATASOURCE_UID:-P8E80F9AEF21F6940}"
token_url="https://idp.${LOCAL_DOMAIN}/realms/${KEYCLOAK_SIGILCORE_REALM}/protocol/openid-connect/token"

tmp_env="/dev/shm/grafana-loki-auth-test.$$"
cleanup() {
  rm -f "$tmp_env"
}
trap cleanup EXIT HUP INT TERM
umask 077
cat > "$tmp_env" <<EOF
GRAFANA_URL=${grafana_url}
GRAFANA_DATASOURCE_UID=${datasource_uid}
GRAFANA_API_TOKEN=${MCP_ADMIN_GRAFANA_API_KEY}
KEYCLOAK_TOKEN_URL=${token_url}
KEYCLOAK_CLIENT_ID=${SIGILCORE_LOKI_API_CLIENT_ID}
KEYCLOAK_CLIENT_SECRET=${SIGILCORE_LOKI_API_CLIENT_SECRET}
EOF

docker run --rm -i --network traefik --env-file "$tmp_env" python:3.12-alpine python - <<'PY'
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def emit(payload):
    print(json.dumps(payload, sort_keys=True))


def request(label, url, *, method="GET", headers=None, data=None, body_limit=160):
    started = time.monotonic()
    status = None
    content_type = None
    body = b""
    error = None
    try:
        req = urllib.request.Request(
            url,
            data=data,
            headers=headers or {},
            method=method,
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            status = response.status
            content_type = response.headers.get("content-type")
            body = response.read() if body_limit is None else response.read(body_limit)
    except urllib.error.HTTPError as exc:
        status = exc.code
        content_type = exc.headers.get("content-type")
        body = exc.read() if body_limit is None else exc.read(body_limit)
    except urllib.error.URLError as exc:
        error = {"type": type(exc).__name__, "reason": str(exc.reason)}
    emit(
        {
            "label": label,
            "status": status,
            "content_type": content_type,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "error": error,
            "body_prefix": "[redacted]" if body_limit is None else body.decode("utf-8", "replace"),
        }
    )
    return status, body


form = urllib.parse.urlencode(
    {
        "grant_type": "client_credentials",
        "client_id": os.environ["KEYCLOAK_CLIENT_ID"],
        "client_secret": os.environ["KEYCLOAK_CLIENT_SECRET"],
    }
).encode()
status, body = request(
    "keycloak_client_credentials",
    os.environ["KEYCLOAK_TOKEN_URL"],
    method="POST",
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    data=form,
    body_limit=None,
)
if status != 200:
    sys.exit(10)

payload = json.loads(body.decode())
token = payload["access_token"]
parts = token.split(".")
claims = {}
if len(parts) >= 2:
    claims = json.loads(base64.urlsafe_b64decode((parts[1] + "=" * (-len(parts[1]) % 4)).encode()))
groups = claims.get("groups") or []
aud = claims.get("aud") or []
if isinstance(aud, str):
    aud = [aud]
emit(
    {
        "label": "loki_token_claim_contract",
        "azp": claims.get("azp"),
        "aud_contains_oauth2_proxy": "oauth2-proxy" in aud,
        "groups_contains_admin": "admin" in groups,
    }
)
if "oauth2-proxy" not in aud or "admin" not in groups:
    sys.exit(11)

grafana_headers = {"Authorization": f"Bearer {os.environ['GRAFANA_API_TOKEN']}"}
base = os.environ["GRAFANA_URL"].rstrip("/")
uid = os.environ["GRAFANA_DATASOURCE_UID"]
status, _ = request(
    "grafana_loki_proxy_buildinfo",
    f"{base}/api/datasources/proxy/uid/{uid}/loki/api/v1/status/buildinfo",
    headers=grafana_headers,
)
if status != 200:
    sys.exit(12)
status, _ = request(
    "grafana_loki_proxy_labels",
    f"{base}/api/datasources/proxy/uid/{uid}/loki/api/v1/labels",
    headers=grafana_headers,
)
if status != 200:
    sys.exit(13)
PY
