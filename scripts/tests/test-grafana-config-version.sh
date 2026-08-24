#!/usr/bin/env bash
set -euo pipefail

export GIT_MASTER=1

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
helper="$repo_root/scripts/grafana-config-version.sh"
submodule_rel='stacks/main/configs/grafana/dashboards/tralmor-grafana-iac'
submodule="$repo_root/$submodule_rel"
expected_sha='aa85188efb63a64a0b43b1a947562f7b7deee048'
baseline_migrated=(
  grafana_datasources
  grafana_dashboards
  grafana_dashboard_docker
  grafana_dashboard_traefik
  grafana_dashboard_nextdns
  grafana_dashboard_docker_swarm
  grafana_dashboard_loki_connection
  grafana_dashboard_system_anomalies
  grafana_dashboard_watchtower
  grafana_dashboard_docker_health_telegraf
  grafana_dashboard_cluster_connection_performance
  grafana_dashboard_postgres_k3s_datastore
  grafana_dashboard_volcano_scheduler_internal
  grafana_dashboard_volcano_scheduler_queue
  grafana_dashboard_k3s_status
)
foreign_exceptions=(
  grafana_alerting_behavioral_rules
  grafana_alerting_contact_points
  grafana_alerting_notification_policies
)

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

expect_line() {
  local expected=$1
  local file=$2
  grep -Fqx "$expected" "$file" || fail "missing exact line: $expected"
}

expect_count() {
  local expected=$1
  local pattern=$2
  local file=$3
  local count
  count=$(grep -Fxc "$pattern" "$file" || true)
  [ "$count" = "$expected" ] || fail "expected $expected occurrence(s) of: $pattern; found $count"
}

mode=working
if [ "${1:-}" = '--from-index' ]; then
  mode=index
  shift
fi
[ "$#" -eq 0 ] || fail 'unsupported argument'

[ -x "$helper" ] || fail 'missing executable scoped version helper'

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT
env_file="$workdir/.env"
before_file="$workdir/before-without-grafana"
after_file="$workdir/after-without-grafana"

printf 'export CONFIG_VERSION=675\nexport KEEP_ME=unchanged\n' >"$env_file"
chmod 640 "$env_file"
cp "$env_file" "$before_file"

"$helper" init --env-file "$env_file" --value 675
expect_line 'export GRAFANA_CONFIG_VERSION=675' "$env_file"
expect_line 'export CONFIG_VERSION=675' "$env_file"
expect_line 'export KEEP_ME=unchanged' "$env_file"
[ "$(stat -c '%a' "$env_file")" = '640' ] || fail 'init changed .env mode'
grep -Fvx 'export GRAFANA_CONFIG_VERSION=675' "$env_file" >"$after_file"
cmp -s "$before_file" "$after_file" || fail 'init changed unrelated .env bytes'

"$helper" bump --env-file "$env_file"
expect_line 'export GRAFANA_CONFIG_VERSION=676' "$env_file"
expect_line 'export CONFIG_VERSION=675' "$env_file"
expect_line 'export KEEP_ME=unchanged' "$env_file"
[ "$(stat -c '%a' "$env_file")" = '640' ] || fail 'bump changed .env mode'
grep -Fvx 'export GRAFANA_CONFIG_VERSION=676' "$env_file" >"$after_file"
cmp -s "$before_file" "$after_file" || fail 'bump changed unrelated .env bytes'

duplicate_env="$workdir/duplicate.env"
printf 'export GRAFANA_CONFIG_VERSION=675\nexport GRAFANA_CONFIG_VERSION=676\n' >"$duplicate_env"
if "$helper" bump --env-file "$duplicate_env"; then
  fail 'bump accepted duplicate Grafana version assignments'
fi

if [ "$mode" = index ]; then
  compose="$workdir/traefik.yml"
  git -C "$repo_root" show ':stacks/main/traefik.yml' >"$compose"
else
  compose="$repo_root/stacks/main/traefik.yml"
fi

gitlink=$(git -C "$repo_root" ls-files --stage -- "$submodule_rel")
printf -v expected_gitlink '160000 %s 0\t%s' "$expected_sha" "$submodule_rel"
if [ "$mode" = index ]; then
  [ "$gitlink" = "$expected_gitlink" ] || fail "parent index lacks exact approved private IaC gitlink: $submodule_rel"
elif [ "$gitlink" != "$expected_gitlink" ]; then
  git -C "$submodule" rev-parse HEAD | grep -Fqx "$expected_sha" || fail 'submodule is not pinned to the approved private IaC commit'
fi

for artifact in cluster-operations-overview ingress-reliability swarm-workload-pressure; do
  artifact_path="$submodule/dist/$artifact.json"
  if [ "$mode" = index ]; then
    git -C "$submodule" show "$expected_sha:dist/$artifact.json" | python3 - "$artifact" 3<&0 <<'PY'
import json
import os
import sys

expected_uid = sys.argv[1]
with os.fdopen(3, encoding='utf-8') as handle:
    payload = json.load(handle)
if not isinstance(payload, dict) or payload.get('uid') != expected_uid or not payload.get('panels'):
    raise SystemExit(f'invalid Grafana dashboard artifact at committed revision: {expected_uid}')
PY
  else
    [ -f "$artifact_path" ] || fail "missing rendered artifact: $artifact"
    python3 - "$artifact_path" "$artifact" <<'PY'
import json
import sys

path, expected_uid = sys.argv[1:]
with open(path, encoding='utf-8') as handle:
    payload = json.load(handle)
if not isinstance(payload, dict) or payload.get('uid') != expected_uid or not payload.get('panels'):
    raise SystemExit(f'invalid Grafana dashboard artifact: {path}')
PY
  fi
done

owned_names=("${baseline_migrated[@]}" grafana_dashboard_cluster_operations_overview grafana_dashboard_ingress_reliability grafana_dashboard_swarm_workload_pressure)
for config_name in "${owned_names[@]}"; do
  printf -v expected_name '    name: %s-${GRAFANA_CONFIG_VERSION:?GRAFANA_CONFIG_VERSION must be set}' "$config_name"
  expect_count 1 "$expected_name" "$compose"
done

scoped_names=$(rg -N '^    name: grafana_[A-Za-z0-9_]+-\$\{GRAFANA_CONFIG_VERSION:\?GRAFANA_CONFIG_VERSION must be set\}$' "$compose" | wc -l | tr -d '[:space:]')
[ "$scoped_names" = '18' ] || fail "expected 18 scoped Grafana config names; found $scoped_names"

for exception in "${foreign_exceptions[@]}"; do
  if grep -Fq "  $exception:" "$compose"; then
    printf -v expected_global '    name: %s-${CONFIG_VERSION:-0}' "$exception"
    expect_count 1 "$expected_global" "$compose"
  fi
done

while IFS= read -r global_line; do
  config_name=$(printf '%s\n' "$global_line" | sed -E 's/^    name: (grafana_[A-Za-z0-9_]+)-\$\{CONFIG_VERSION:-0\}$/\1/')
  case "$config_name" in
    grafana_alerting_behavioral_rules|grafana_alerting_contact_points|grafana_alerting_notification_policies) ;;
    *) fail "unexpected global Grafana config version: $config_name" ;;
  esac
done < <(rg -N '^    name: grafana_[A-Za-z0-9_]+-\$\{CONFIG_VERSION:-0\}$' "$compose" || true)

if [ "$mode" = index ]; then
  for exception in "${foreign_exceptions[@]}"; do
    grep -Fq "  $exception:" "$compose" && fail "foreign alerting config staged: $exception"
  done
fi

for artifact in cluster-operations-overview ingress-reliability swarm-workload-pressure; do
  config_name="grafana_dashboard_${artifact//-/_}"
  expect_count 1 "  $config_name:" "$compose"
  expect_count 1 "    - source: $config_name" "$compose"
  expect_count 1 "      target: /etc/grafana/provisioning/dashboards/custom/$artifact.json" "$compose"
  expect_count 1 "    file: ./configs/grafana/dashboards/tralmor-grafana-iac/dist/$artifact.json" "$compose"
done

expect_line 'export GRAFANA_CONFIG_VERSION=1' "$repo_root/.env.example"
printf 'PASS: Grafana IaC integration contract (%s)\n' "$mode"
