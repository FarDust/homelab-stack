#!/bin/sh
set -eu

TARGET="${INOTIFY_MAX_USER_INSTANCES:-1024}"
INTERVAL="${INOTIFY_RECONCILE_INTERVAL:-300}"
CONF_FILE="/host-etc-sysctl/99-tralmor-inotify.conf"
SYSCTL_FILE="/host-proc-sys/fs/inotify/max_user_instances"

write_conf() {
  tmp="$(mktemp)"
  {
    echo "# Managed by main-maintenance_inotify-sysctl-reconciler"
    echo "fs.inotify.max_user_instances=${TARGET}"
  } > "${tmp}"
  cat "${tmp}" > "${CONF_FILE}"
  rm -f "${tmp}"
}

apply_runtime() {
  if [ -w "${SYSCTL_FILE}" ]; then
    current="$(cat "${SYSCTL_FILE}" 2>/dev/null || echo unknown)"
    if [ "${current}" != "${TARGET}" ]; then
      echo "${TARGET}" > "${SYSCTL_FILE}"
      echo "updated_runtime from=${current} to=${TARGET}"
    fi
  else
    echo "warn_runtime_not_writable path=${SYSCTL_FILE}"
  fi
}

write_conf
apply_runtime

while true; do
  write_conf
  apply_runtime
  sleep "${INTERVAL}"
done
