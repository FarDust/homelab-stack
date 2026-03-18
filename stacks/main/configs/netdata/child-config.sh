#!/bin/sh
set -eu

HOST_NETDATA_DIR="${NETDATA_CHILD_TARGET:-/host/etc/netdata}"
STREAM_CONF="${HOST_NETDATA_DIR}/stream.conf"
STREAM_KEY_FILE="/run/secrets/netdata_stream_api_key"
INTERVAL="${NETDATA_CHILD_CONFIG_INTERVAL:-300}"
RUN_ONCE="${NETDATA_CHILD_CONFIG_ONCE:-false}"

write_stream_conf() {
  if [ ! -d "${HOST_NETDATA_DIR}" ]; then
    echo "netdata-child-config: ${HOST_NETDATA_DIR} not found, skipping."
    return 0
  fi

  if [ ! -f "${STREAM_KEY_FILE}" ]; then
    echo "netdata-child-config: missing ${STREAM_KEY_FILE}"
    return 1
  fi

  STREAM_KEY="$(cat "${STREAM_KEY_FILE}")"
  DEST_HOST="${NETDATA_PARENT_HOST:-netdata.${LOCAL_DOMAIN:?err}}"
  DEST_PORT="${NETDATA_PARENT_PORT:-5578}"

  TMP_FILE="$(mktemp)"
  cat <<EOF > "${TMP_FILE}"
# Netdata child stream.conf (managed by netdata-child-config)
[stream]
  enabled = yes
  destination = ${DEST_HOST}:${DEST_PORT}:SSL
  api key = ${STREAM_KEY}
  ssl skip certificate verification = yes
EOF

  if [ -f "${STREAM_CONF}" ] && cmp -s "${TMP_FILE}" "${STREAM_CONF}"; then
    echo "netdata-child-config: ${STREAM_CONF} already up to date."
    rm -f "${TMP_FILE}"
    return 0
  fi

  install -m 0644 "${TMP_FILE}" "${STREAM_CONF}"
  rm -f "${TMP_FILE}"
  echo "netdata-child-config: wrote ${STREAM_CONF}"
  return 0
}

if [ "${RUN_ONCE}" = "true" ] || [ "${INTERVAL}" -eq 0 ] 2>/dev/null; then
  write_stream_conf
  exit $?
fi

while true; do
  write_stream_conf || true
  sleep "${INTERVAL}"
done
