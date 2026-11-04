#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

workdir="/dev/shm/loki-service-log-coverage.$$"
cleanup() { rm -rf "$workdir"; }
trap cleanup EXIT HUP INT TERM
umask 077
mkdir -p "$workdir"

emit_json() {
  python3 - "$@" <<'PY'
import json
import sys

payload = {}
for arg in sys.argv[1:]:
    key, value = arg.split("=", 1)
    if value.isdigit():
        payload[key] = int(value)
    elif value in {"true", "false"}:
        payload[key] = value == "true"
    else:
        payload[key] = value
print(json.dumps(payload, sort_keys=True))
PY
}

set -a
. ./.env
set +a

: "${MCP_ADMIN_GRAFANA_API_KEY:?MCP_ADMIN_GRAFANA_API_KEY is required}"

grafana_url="${GRAFANA_URL:-http://grafana:3000}"
datasource_uid="${GRAFANA_LOKI_DATASOURCE_UID:-P8E80F9AEF21F6940}"

tmp_env="$workdir/grafana.env"
cat > "$tmp_env" <<ENVEOF
GRAFANA_URL=${grafana_url}
GRAFANA_DATASOURCE_UID=${datasource_uid}
GRAFANA_API_TOKEN=${MCP_ADMIN_GRAFANA_API_KEY}
ENVEOF

docker service ps main-logging_vector --no-trunc --filter desired-state=running --format '{{.Node}} {{.CurrentState}}' \
  | awk '$2 ~ /^Running/ {print $1}' \
  | sort -u > "$workdir/vector_nodes.txt"

docker node ls --format '{{.Hostname}} {{.Status}} {{.Availability}}' \
  | awk '$2 == "Ready" && $3 == "Active" {print $1}' \
  | sort -u > "$workdir/ready_active_nodes.txt"

ready_active_count=$(wc -l < "$workdir/ready_active_nodes.txt")
vector_node_count=$(wc -l < "$workdir/vector_nodes.txt")
emit_json label=vector_node_coverage ready_active_nodes="$ready_active_count" vector_nodes="$vector_node_count"

if ! comm -23 "$workdir/ready_active_nodes.txt" "$workdir/vector_nodes.txt" > "$workdir/ready_nodes_without_vector.txt"; then
  exit 20
fi
if [ -s "$workdir/ready_nodes_without_vector.txt" ]; then
  sed 's/^/missing_vector_node: /' "$workdir/ready_nodes_without_vector.txt" >&2
  exit 14
fi

docker service ls --format '{{.Name}} {{.Replicas}}' > "$workdir/services.txt"
while read -r service _replicas; do
  [ -n "$service" ] || continue
  docker service ps "$service" --no-trunc --format '{{.Node}}|{{.DesiredState}}|{{.CurrentState}}|{{.Error}}' \
    | awk -v svc="$service" -F'|' 'BEGIN{OFS="|"} {print svc,$1,$2,$3,$4}'
done < "$workdir/services.txt" > "$workdir/tasks.psv"

awk -F'|' 'tolower($4) ~ /^running/ {print $1"|"$2}' "$workdir/tasks.psv" \
  | sort -u > "$workdir/running_service_nodes.psv"

awk -F'|' 'NR==FNR{v[$1]=1; next} ($2 in v){print $1}' \
  "$workdir/vector_nodes.txt" "$workdir/running_service_nodes.psv" \
  | sort -u > "$workdir/expected_services.txt"

awk -F'|' 'NR==FNR{v[$1]=1; next} !($2 in v){print $0}' \
  "$workdir/vector_nodes.txt" "$workdir/running_service_nodes.psv" \
  | sort -u > "$workdir/uncovered_running_service_nodes.psv"

uncovered_count=$(wc -l < "$workdir/uncovered_running_service_nodes.psv")
expected_count=$(wc -l < "$workdir/expected_services.txt")
emit_json label=swarm_service_node_coverage expected_services="$expected_count" uncovered_running_service_nodes="$uncovered_count"
if [ "$uncovered_count" -ne 0 ]; then
  sed 's/^/uncovered_running_service_node: /' "$workdir/uncovered_running_service_nodes.psv" >&2
  exit 15
fi

docker run --rm -i --network traefik --env-file "$tmp_env" python:3.12-alpine python - <<'PY' > "$workdir/loki_values.txt"
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def emit(payload):
    print(json.dumps(payload, sort_keys=True), file=sys.stderr)


def request_json(label, path):
    base = os.environ["GRAFANA_URL"].rstrip("/")
    uid = os.environ["GRAFANA_DATASOURCE_UID"]
    url = f"{base}/api/datasources/proxy/uid/{uid}{path}"
    started = time.monotonic()
    status = None
    body = b""
    error = None
    try:
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {os.environ['GRAFANA_API_TOKEN']}"},
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            status = response.status
            body = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read(512)
    except urllib.error.URLError as exc:
        error = {"type": type(exc).__name__, "reason": str(exc.reason)}
    payload = None
    if body and status == 200:
        payload = json.loads(body.decode())
    emit({"label": label, "status": status, "elapsed_ms": round((time.monotonic() - started) * 1000), "error": error})
    return status, payload


status, labels_payload = request_json("loki_service_name_values", "/loki/api/v1/label/service_name/values")
if status != 200 or labels_payload is None:
    sys.exit(10)
values = sorted(str(item) for item in labels_payload.get("data", []))
for value in values:
    print(value)
non_traefik_values = [item for item in values if item != "traefik"]
emit({"label": "loki_service_name_coverage", "service_name_count": len(values), "non_traefik_count": len(non_traefik_values), "sample": values[:12]})
if len(non_traefik_values) < 3:
    sys.exit(11)

query = urllib.parse.urlencode({"query": '{job="docker",service_name!="traefik"}', "limit": "5"})
status, query_payload = request_json("loki_non_traefik_log_query", f"/loki/api/v1/query_range?{query}")
if status != 200 or query_payload is None:
    sys.exit(12)
streams = query_payload.get("data", {}).get("result", [])
emit({"label": "loki_non_traefik_log_streams", "stream_count": len(streams)})
if not streams:
    sys.exit(13)
PY

sort -u "$workdir/loki_values.txt" -o "$workdir/loki_values.txt"
comm -23 "$workdir/expected_services.txt" "$workdir/loki_values.txt" > "$workdir/missing_services.txt"

while read -r service; do
  [ -n "$service" ] || continue
  if timeout 8s docker service logs --raw --since 5m --tail 1 "$service" > "$workdir/one.log" 2>/dev/null && [ -s "$workdir/one.log" ]; then
    printf '%s\n' "$service"
  fi
done < "$workdir/missing_services.txt" > "$workdir/missing_with_recent_docker_logs.txt"

missing_total=$(wc -l < "$workdir/missing_services.txt")
missing_with_logs=$(wc -l < "$workdir/missing_with_recent_docker_logs.txt")
quiet_missing=$((missing_total - missing_with_logs))
emit_json label=loki_missing_service_classification missing_total="$missing_total" missing_with_recent_docker_logs="$missing_with_logs" quiet_missing="$quiet_missing"

if [ "$missing_with_logs" -ne 0 ]; then
  sed 's/^/missing_loki_label_with_recent_docker_logs: /' "$workdir/missing_with_recent_docker_logs.txt" >&2
  exit 16
fi
