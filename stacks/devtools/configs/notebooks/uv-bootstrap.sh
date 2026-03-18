#!/usr/bin/env bash

uv_bootstrap_main() {
set -euo pipefail

if [[ "${UV_BOOTSTRAP_ENABLED:-true}" != "true" ]]; then
  echo "[uv-bootstrap] disabled via UV_BOOTSTRAP_ENABLED=${UV_BOOTSTRAP_ENABLED:-}"
  exit 0
fi

NB_USER="${NB_USER:-jovyan}"

# Jupyter Docker Stacks may execute hooks as root; switch to notebook user for user-level installs.
if [[ "$(id -u)" -eq 0 ]]; then
  exec su "${NB_USER}" -s /bin/bash -c "$0"
fi

NB_HOME="${HOME:-/home/${NB_USER}}"
export HOME="${NB_HOME}"
export PATH="${NB_HOME}/.local/bin:${PATH}"
export UV_LINK_MODE="${UV_LINK_MODE:-copy}"

mkdir -p \
  "${NB_HOME}/work" \
  "${NB_HOME}/.local/bin" \
  "${NB_HOME}/.local/share/jupyter/kernels" \
  "${NB_HOME}/.venvs"

STATE_DIR="${NB_HOME}/.venvs/.colab-runtime"
mkdir -p "${STATE_DIR}"
UV_HOME_BIN="${NB_HOME}/.local/bin/uv"
UV_RUN_BIN="/tmp/uv-${NB_USER}"
LOCK_DIR="${STATE_DIR}/uv-bootstrap.lock"

checksum() {
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s\n' "$*" | sha256sum | awk '{print $1}'
    return
  fi

  if command -v shasum >/dev/null 2>&1; then
    printf '%s\n' "$*" | shasum -a 256 | awk '{print $1}'
    return
  fi

  python3 - <<'PY'
import hashlib, sys
print(hashlib.sha256(sys.stdin.read().encode()).hexdigest())
PY
}

if [[ ! -x "${UV_HOME_BIN}" ]]; then
  echo "[uv-bootstrap] installing uv for ${NB_USER}"
  python3 -m pip install --user --upgrade uv
fi

if [[ ! -x "${UV_RUN_BIN}" || "${UV_HOME_BIN}" -nt "${UV_RUN_BIN}" ]]; then
  cp "${UV_HOME_BIN}" "${UV_RUN_BIN}"
  chmod 0755 "${UV_RUN_BIN}"
fi

acquire_lock() {
  local tries=0
  while ! mkdir "${LOCK_DIR}" 2>/dev/null; do
    tries=$((tries + 1))
    if [[ "${tries}" -ge 120 ]]; then
      echo "[uv-bootstrap] lock timeout after ${tries}s: ${LOCK_DIR}" >&2
      exit 1
    fi
    sleep 1
  done

  trap 'rmdir "${LOCK_DIR}" 2>/dev/null || true' EXIT
}

ensure_env() {
  local env_name="$1"
  local display_name="$2"
  shift 2

  local env_dir="${NB_HOME}/.venvs/${env_name}"
  local py_bin="${env_dir}/bin/python"
  local marker_file="${STATE_DIR}/${env_name}.sha256"

  if [[ ! -x "${py_bin}" ]]; then
    rm -rf "${env_dir}"
    python3 -m venv --copies "${env_dir}"
  fi

  local new_hash
  new_hash="$(checksum "$*")"

  local old_hash=""
  if [[ -f "${marker_file}" ]]; then
    old_hash="$(cat "${marker_file}")"
  fi

  local needs_sync="false"
  if [[ "${new_hash}" != "${old_hash}" ]]; then
    needs_sync="true"
  fi

  # Marker may claim "up-to-date" while environment is partially corrupted on shared storage.
  if [[ "${needs_sync}" != "true" ]] && ! "${py_bin}" -c "import ipykernel" >/dev/null 2>&1; then
    echo "[uv-bootstrap] detected unhealthy ${env_name} (ipykernel import failed), forcing resync"
    needs_sync="true"
  fi

  if [[ "${needs_sync}" == "true" ]]; then
    echo "[uv-bootstrap] syncing packages for ${env_name}"
    if ! "${UV_RUN_BIN}" pip install --reinstall --python "${py_bin}" "$@"; then
      echo "[uv-bootstrap] sync failed for ${env_name}, rebuilding clean environment"
      rm -rf "${env_dir}"
      python3 -m venv --copies "${env_dir}"
      py_bin="${env_dir}/bin/python"
      "${UV_RUN_BIN}" pip install --python "${py_bin}" "$@"
    fi
    printf '%s\n' "${new_hash}" > "${marker_file}"
  else
    echo "[uv-bootstrap] package set unchanged for ${env_name}"
  fi

  "${py_bin}" -m ipykernel install --user --name "${env_name}" --display-name "${display_name}" >/dev/null
}

acquire_lock

ensure_env "py311-base" "Python 3.11 (uv base)" \
  ipykernel numpy pandas

ensure_env "py311-ds" "Python 3.11 (uv ds)" \
  ipykernel numpy pandas scikit-learn matplotlib seaborn

echo "[uv-bootstrap] bootstrap complete"
}

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  (uv_bootstrap_main)
  return $?
fi

uv_bootstrap_main
