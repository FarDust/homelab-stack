#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
helper="${repo_root}/scripts/grafana-config-version.sh"
compose_file="${repo_root}/stacks/main/traefik.yml"
submodule_path='stacks/main/configs/grafana/dashboards/tralmor-grafana-iac'
submodule_dir="${repo_root}/${submodule_path}"
expected_sha='96488f86e313843a0eb23a70fe7d466b5d8df314'

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

assert_file_equals() {
  local expected="$1"
  local actual="$2"
  local message="$3"
  cmp -s "${expected}" "${actual}" || fail "${message}"
}

tmp_dir="$(mktemp -d)"
trap 'rm -rf -- "${tmp_dir}"' EXIT INT TERM
normalized_compose="${tmp_dir}/traefik.yml"
sed 's/\r$//' "${compose_file}" > "${normalized_compose}"

help_dir="${tmp_dir}/help"
mkdir "${help_dir}"
printf 'sentinel\r\n' > "${help_dir}/sentinel"
cp "${help_dir}/sentinel" "${help_dir}/sentinel.before"
help_before="$(find "${help_dir}" -maxdepth 1 -type f -printf '%f\n' | sort)"
help_output="$(cd "${help_dir}" && "${helper}" --help)"
help_after="$(find "${help_dir}" -maxdepth 1 -type f -printf '%f\n' | sort)"
[[ -n "${help_output}" ]] || fail '--help must print usage information'
[[ "${help_after}" == "${help_before}" ]] || fail '--help must not create or modify files'
assert_file_equals "${help_dir}/sentinel.before" "${help_dir}/sentinel" '--help changed existing file bytes'

env_file="${tmp_dir}/explicit.env"
initialized_file="${tmp_dir}/explicit.initialized"
expected_file="${tmp_dir}/explicit.expected"
printf 'export CONFIG_VERSION=73\r\nUNCHANGED=value  ' > "${env_file}"
chmod 0604 "${env_file}"
printf 'export CONFIG_VERSION=73\r\nUNCHANGED=value  \nexport GRAFANA_CONFIG_VERSION=675\n' > "${initialized_file}"
output="$("${helper}" init --env-file "${env_file}" --value 675)"
[[ "${output}" == 'GRAFANA_CONFIG_VERSION=675' ]] || fail 'init must print only the seeded assignment'
assert_file_equals "${initialized_file}" "${env_file}" 'init changed unrelated bytes'
[[ "$(stat -c '%a' "${env_file}")" == '604' ]] || fail 'init changed the file mode'

printf 'export CONFIG_VERSION=73\r\nUNCHANGED=value  \nexport GRAFANA_CONFIG_VERSION=676\n' > "${expected_file}"
output="$("${helper}" bump --env-file "${env_file}")"
[[ "${output}" == 'GRAFANA_CONFIG_VERSION=676' ]] || fail 'bump must print only the incremented assignment'
assert_file_equals "${expected_file}" "${env_file}" 'bump changed bytes outside the Grafana version'
[[ "$(stat -c '%a' "${env_file}")" == '604' ]] || fail 'bump changed the file mode'

invalid_init="${tmp_dir}/invalid-init.env"
if "${helper}" init --env-file "${invalid_init}" --value 0 > "${tmp_dir}/invalid-init.stdout" 2> "${tmp_dir}/invalid-init.stderr"; then
  fail 'init must reject non-positive values'
fi
[[ ! -e "${invalid_init}" ]] || fail 'rejected init created an env file'
[[ ! -s "${tmp_dir}/invalid-init.stdout" ]] || fail 'rejected init must not print an assignment'

env_file="${tmp_dir}/duplicate.env"
duplicate_before="${tmp_dir}/duplicate.before"
printf 'GRAFANA_CONFIG_VERSION=1\nexport GRAFANA_CONFIG_VERSION=2\nCONFIG_VERSION=99\n' > "${env_file}"
chmod 0644 "${env_file}"
cp "${env_file}" "${duplicate_before}"
if "${helper}" bump --env-file "${env_file}" > "${tmp_dir}/duplicate.stdout" 2> "${tmp_dir}/duplicate.stderr"; then
  fail 'duplicate Grafana version assignments must be rejected'
fi
[[ ! -s "${tmp_dir}/duplicate.stdout" ]] || fail 'duplicate rejection must not print a version'
assert_file_equals "${duplicate_before}" "${env_file}" 'duplicate rejection changed the env file'
[[ "$(stat -c '%a' "${env_file}")" == '644' ]] || fail 'duplicate rejection changed the file mode'

env_file="${tmp_dir}/malformed.env"
malformed_before="${tmp_dir}/malformed.before"
printf 'CONFIG_VERSION=99\nexport GRAFANA_CONFIG_VERSION=not-a-number\nKEEP=this\n' > "${env_file}"
chmod 0640 "${env_file}"
cp "${env_file}" "${malformed_before}"
if "${helper}" bump --env-file "${env_file}" > "${tmp_dir}/malformed.stdout" 2> "${tmp_dir}/malformed.stderr"; then
  fail 'bump must reject malformed Grafana version assignments'
fi
[[ ! -s "${tmp_dir}/malformed.stdout" ]] || fail 'malformed rejection must not print an assignment'
assert_file_equals "${malformed_before}" "${env_file}" 'malformed rejection changed the env file'
[[ "$(stat -c '%a' "${env_file}")" == '640' ]] || fail 'malformed rejection changed the file mode'

gitlink="$(git -C "${repo_root}" ls-files --stage -- "${submodule_path}")"
expected_gitlink="160000 ${expected_sha} 0"$'\t'"${submodule_path}"
[[ "${gitlink}" == "${expected_gitlink}" ]] || fail 'submodule gitlink is not pinned to the approved commit'

gitmodules_url="$(git -C "${repo_root}" config -f .gitmodules --get "submodule.${submodule_path}.url")"
[[ "${gitmodules_url}" == 'https://github.com/FarDust/tralmor-grafana-iac.git' ]] || fail 'submodule URL must be credential-free HTTPS'

dist_dir="${submodule_dir}/dist"
actual_artifacts="$({
  for artifact in "${dist_dir}"/*; do
    [[ -f "${artifact}" ]] || fail 'dist must contain only regular artifact files'
    basename "${artifact}"
  done
} | sort)"
expected_artifacts=$'cluster-operations-overview.json\ningress-reliability.json'
[[ "${actual_artifacts}" == "${expected_artifacts}" ]] || fail 'submodule dist artifacts do not match the approved set'

expected_configs=(
  grafana_dashboard_cluster_connection_performance
  grafana_dashboard_cluster_operations_overview
  grafana_dashboard_docker
  grafana_dashboard_docker_health_telegraf
  grafana_dashboard_docker_swarm
  grafana_dashboard_ingress_reliability
  grafana_dashboard_k3s_status
  grafana_dashboard_loki_connection
  grafana_dashboard_nextdns
  grafana_dashboard_postgres_k3s_datastore
  grafana_dashboard_system_anomalies
  grafana_dashboard_traefik
  grafana_dashboard_volcano_scheduler_internal
  grafana_dashboard_volcano_scheduler_queue
  grafana_dashboard_watchtower
  grafana_dashboards
  grafana_datasources
)
expected_config_list="$(printf '%s\n' "${expected_configs[@]}" | sort)"

actual_service_configs="$(
  sed -n '/^  grafana:/,/^  agent:/p' "${normalized_compose}" |
    sed -n '/^    configs:/,/^    secrets:/p' |
    sed -n 's/^    - source: \(grafana_[a-z0-9_]*\)$/\1/p' |
    sort
)"
[[ "${actual_service_configs}" == "${expected_config_list}" ]] || fail 'Grafana service must mount exactly the 17 scoped configs'

actual_definitions="$(
  sed -n '/^configs:/,/^secrets:/p' "${normalized_compose}" |
    sed -n 's/^  \(grafana_[a-z0-9_]*\):$/\1/p' |
    sort
)"
[[ "${actual_definitions}" == "${expected_config_list}" ]] || fail 'top-level configs must define exactly the 17 scoped Grafana configs'

for config_name in "${expected_configs[@]}"; do
  expected_name="    name: ${config_name}-\${GRAFANA_CONFIG_VERSION:?GRAFANA_CONFIG_VERSION must be set}"
  [[ "$(grep -Fxc "${expected_name}" "${normalized_compose}")" == '1' ]] || fail "${config_name} does not use the scoped version"
done

[[ "$(grep -Fxc '      target: /etc/grafana/provisioning/dashboards/custom/cluster-operations-overview.json' "${normalized_compose}")" == '1' ]] || fail 'cluster operations mount target is not exact'
[[ "$(grep -Fxc '      target: /etc/grafana/provisioning/dashboards/custom/ingress-reliability.json' "${normalized_compose}")" == '1' ]] || fail 'ingress reliability mount target is not exact'
[[ "$(grep -Fxc '    file: ./configs/grafana/dashboards/tralmor-grafana-iac/dist/cluster-operations-overview.json' "${normalized_compose}")" == '1' ]] || fail 'cluster operations artifact source is not exact'
[[ "$(grep -Fxc '    file: ./configs/grafana/dashboards/tralmor-grafana-iac/dist/ingress-reliability.json' "${normalized_compose}")" == '1' ]] || fail 'ingress reliability artifact source is not exact'

[[ "$(grep -Fc 'GRAFANA_CONFIG_VERSION:?GRAFANA_CONFIG_VERSION must be set' "${normalized_compose}")" == '17' ]] || fail 'scoped Grafana version must appear exactly 17 times'
[[ "$(grep -Fxc 'export GRAFANA_CONFIG_VERSION=1' "${repo_root}/.env.example")" == '1' ]] || fail '.env.example must initialize the Grafana config version once'

printf 'PASS: Grafana config version integration\n'
