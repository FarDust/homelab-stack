#!/bin/bash
# Canonical FILE/rclone backup payload for the four existing PostgreSQL services.
set -euo pipefail
umask 077
export LC_ALL=C
root=${BACKUP_ROOT:-/backups}
lock=${BACKUP_LOCK:-/run/postgres-backup.lock}
mode=${1:-run}

write_atomic() {
  target="$1"
  shift
  partial="${target}.partial"
  printf '%s\n' "$*" > "$partial"
  mv -f -- "$partial" "$target"
}

backup_root_available() {
  mkdir -p "$root" 2>/dev/null \
    && stat "$root" >/dev/null 2>&1 \
    && find "$root" -maxdepth 0 -type d -print -quit >/dev/null 2>&1
}

backup_status() {
  threshold=${BACKUP_STALE_SECONDS:-108000}
  now=$(date +%s)
  status_reason=fresh
  age=-1
  archive_count=0
  expected_count=0
  stamp=unknown
  if ! backup_root_available; then
    status_reason=backup-root-unavailable
    echo 'BACKUP|backup-root-unavailable'
    return 70
  fi
  if [[ ! -s "$root/last-success" ]]; then
    status_reason=no-success-receipt
    echo 'BACKUP|no-success-receipt'
    return 1
  fi
  read -r epoch < "$root/last-success"
  if [[ ! "$epoch" =~ ^[0-9]+$ ]]; then
    status_reason=invalid-success-receipt
    echo 'BACKUP|invalid-success-receipt'
    return 1
  fi
  age=$(( now - epoch ))
  if (( age < 0 || age > threshold )); then
    status_reason=stale
    echo "BACKUP|stale|age_seconds=$age|threshold_seconds=$threshold"
    return 1
  fi
  if [[ -s "$root/last-failure" ]]; then
    IFS='|' read -r failure_epoch failure_phase failure_exit < "$root/last-failure" || true
    status_reason=failed-last-attempt
    echo "BACKUP|failed-last-attempt|phase=${failure_phase:-unknown}|exit=${failure_exit:-unknown}|success_age_seconds=$age"
    return 1
  fi
  if [[ ! -s "$root/globals.sql" ]]; then
    status_reason=storage-missing-globals
    echo 'BACKUP|storage-missing-globals'
    return 1
  fi
  if [[ -s "$root/last-success-stamp" ]]; then
    read -r stamp < "$root/last-success-stamp"
  else
    stamp=$(date -u -d "@$epoch" '+%d-%B-%Y')
  fi
  if [[ -s "$root/last-success-directory" ]]; then
    read -r directory < "$root/last-success-directory"
  else
    directory="$root/$(date -u -d "@$epoch" '+%Y/%B')"
  fi
  if [[ -s "$root/last-success-count" ]]; then
    read -r expected_count < "$root/last-success-count"
  else
    expected_count=1
  fi
  if [[ ! "$expected_count" =~ ^[0-9]+$ ]]; then
    status_reason=invalid-success-count
    echo 'BACKUP|invalid-success-count'
    return 1
  fi
  archive_count=$(find "$directory" -maxdepth 1 -type f -name "PG_*.$stamp.dmp" 2>/dev/null | wc -l | tr -d ' ')
  if (( archive_count < expected_count )); then
    status_reason=storage-missing-archives
    echo "BACKUP|storage-missing-archives|visible=$archive_count|expected=$expected_count|stamp=$stamp"
    return 1
  fi
  echo "BACKUP|fresh-mounted-receipt|age_seconds=$age|visible_archives=$archive_count|expected_archives=$expected_count|stamp=$stamp"
  return 0
}

emit_metrics() {
  service=${BACKUP_SERVICE_NAME:-postgres-backup}
  metrics_file=${BACKUP_METRICS_FILE:-}
  [[ -n "$metrics_file" ]] || { backup_status; return $?; }
  set +e
  output=$(backup_status 2>&1)
  rc=$?
  set -e
  reason=$(printf '%s\n' "$output" | head -n 1 | cut -d'|' -f2)
  [[ -n "$reason" ]] || reason=unknown
  ok=0
  if (( rc == 0 )); then ok=1; fi
  age=-1
  visible=0
  expected=0
  if [[ "$output" =~ age_seconds=([-0-9]+) ]]; then age=${BASH_REMATCH[1]}; fi
  if [[ "$output" =~ visible_archives=([0-9]+) ]]; then visible=${BASH_REMATCH[1]}; fi
  if [[ "$output" =~ expected_archives=([0-9]+) ]]; then expected=${BASH_REMATCH[1]}; fi
  mkdir -p "$(dirname "$metrics_file")"
  tmp="${metrics_file}.partial"
  cat > "$tmp" <<METRICS
# HELP postgres_backup_status_ok Backup mounted receipt and publication visibility status; 1 is healthy.
# TYPE postgres_backup_status_ok gauge
postgres_backup_status_ok{service="$service",reason="$reason"} $ok
# HELP postgres_backup_last_success_age_seconds Age in seconds of last successful backup receipt, or -1 when unavailable.
# TYPE postgres_backup_last_success_age_seconds gauge
postgres_backup_last_success_age_seconds{service="$service"} $age
# HELP postgres_backup_visible_archives Count of visible current-stamp archives for the last successful backup.
# TYPE postgres_backup_visible_archives gauge
postgres_backup_visible_archives{service="$service"} $visible
# HELP postgres_backup_expected_archives Expected archive count recorded by the last successful backup.
# TYPE postgres_backup_expected_archives gauge
postgres_backup_expected_archives{service="$service"} $expected
METRICS
  chmod 0644 "$tmp"
  mv -f -- "$tmp" "$metrics_file"
  printf '%s\n' "$output"
  return 0
}

case "$mode" in
  --help)
    echo 'Usage: postgres-backup.sh {schedule|run|status|status-metrics|--help}'
    exit 0 ;;
  schedule)
    : "${POSTGRES_PASS_FILE:?}" "${POSTGRES_HOST:?}" "${POSTGRES_USER:?}"
    : "${POSTGRES_DB:?}" "${PGSSLMODE:?}" "${CRON_SCHEDULE:?}"
    export BACKUP_SCRIPT_PATH="${BACKUP_SCRIPT_PATH:-/maintenance/postgres-backup.sh}"
    for key in POSTGRES_PASS_FILE POSTGRES_HOST POSTGRES_PORT POSTGRES_USER POSTGRES_DB PGSSLMODE BACKUP_ROOT BACKUP_LOCK BACKUP_STALE_SECONDS BACKUP_SERVICE_NAME BACKUP_METRICS_FILE BACKUP_STATUS_INTERVAL_SECONDS BACKUP_STATUS_TIMEOUT_SECONDS BACKUP_ROOT_FAILURE_EXIT_COUNT BACKUP_SCRIPT_PATH TZ; do
      printf 'export %s=%q\n' "$key" "${!key-}"
    done > /run/postgres-backup.env
    cat > /run/postgres-backup-run.sh <<'RUNNER'
#!/bin/bash
set -euo pipefail
. /run/postgres-backup.env
exec timeout --signal=TERM --kill-after=30s 6h /bin/bash "$BACKUP_SCRIPT_PATH" run
RUNNER
    chmod 0700 /run/postgres-backup-run.sh
    schedule=${CRON_SCHEDULE//\"/}
    [[ "$schedule" =~ ^[0-9\*\ /,\-]+$ ]] || { echo 'BACKUP|invalid-schedule' >&2; exit 2; }
    printf '%s /run/postgres-backup-run.sh >> /proc/1/fd/1 2>&1\n' "$schedule" | crontab -
    observer_pid=''
    if [[ -n "${BACKUP_METRICS_FILE:-}" ]]; then
      (
        . /run/postgres-backup.env
        backup_root_failures=0
        backup_root_failure_limit=${BACKUP_ROOT_FAILURE_EXIT_COUNT:-3}
        while true; do
          set +e
          status_output=$(timeout --signal=TERM --kill-after=10s "${BACKUP_STATUS_TIMEOUT_SECONDS:-60s}" /bin/bash "$BACKUP_SCRIPT_PATH" status-metrics 2>&1)
          status_rc=$?
          set -e
          printf '%s\n' "$status_output"
          if printf '%s\n' "$status_output" | grep -qx 'BACKUP|backup-root-unavailable'; then
            backup_root_failures=$((backup_root_failures + 1))
            echo "BACKUP|scheduler-exit-pending|reason=backup-root-unavailable|count=$backup_root_failures|limit=$backup_root_failure_limit"
            if (( backup_root_failures >= backup_root_failure_limit )); then
              echo "BACKUP|scheduler-exit|reason=backup-root-unavailable|count=$backup_root_failures"
              exit 70
            fi
          else
            backup_root_failures=0
          fi
          if (( status_rc != 0 )); then
            echo "BACKUP|status-metrics-command-failed|exit=$status_rc"
          fi
          sleep "${BACKUP_STATUS_INTERVAL_SECONDS:-300}"
        done
      ) &
      observer_pid=$!
    fi
    echo "BACKUP|scheduler-ready|schedule=$schedule"
    cron -f &
    cron_pid=$!
    shutdown_children() {
      rc=${1:-143}
      if [[ -n "$observer_pid" ]]; then kill "$observer_pid" 2>/dev/null || true; fi
      kill "$cron_pid" 2>/dev/null || true
      wait "$cron_pid" 2>/dev/null || true
      if [[ -n "$observer_pid" ]]; then wait "$observer_pid" 2>/dev/null || true; fi
      exit "$rc"
    }
    trap 'shutdown_children 143' TERM INT
    while true; do
      if ! kill -0 "$cron_pid" 2>/dev/null; then
        wait "$cron_pid"
        exit $?
      fi
      if [[ -n "$observer_pid" ]] && ! kill -0 "$observer_pid" 2>/dev/null; then
        set +e
        wait "$observer_pid"
        observer_rc=$?
        set -e
        kill "$cron_pid" 2>/dev/null || true
        wait "$cron_pid" 2>/dev/null || true
        exit "$observer_rc"
      fi
      sleep 1
    done ;;
  status)
    backup_status
    exit $? ;;
  status-metrics)
    emit_metrics
    exit $? ;;
  run) ;;
  *) echo 'BACKUP|invalid-mode' >&2; exit 2 ;;
esac

exec 9> "$lock"
flock -n 9 || { echo 'BACKUP|overlap-rejected' >&2; exit 75; }
: "${POSTGRES_PASS_FILE:?}" "${POSTGRES_HOST:?}" "${POSTGRES_USER:?}" "${POSTGRES_DB:?}" "${PGSSLMODE:?}"
attempt_epoch=$(date +%s)
phase=backup-root
backup_root_available || { echo 'BACKUP|backup-root-unavailable' >&2; exit 70; }
write_atomic "$root/last-attempt" "$attempt_epoch"
export PGPASSWORD
PGPASSWORD=$(cat "$POSTGRES_PASS_FILE")
export PGCONNECT_TIMEOUT=15
conn=(-h "$POSTGRES_HOST" -p "${POSTGRES_PORT:-5432}" -U "$POSTGRES_USER")
stage=$(mktemp -d)
partial=''
phase=inventory
cleanup() {
  rc=$?
  trap - EXIT
  rm -rf "$stage"
  if [[ -n "$partial" ]]; then rm -f -- "$partial"; fi
  if (( rc != 0 )); then
    if backup_root_available; then
      failure_partial="$root/.last-failure.partial"
      printf '%s|%s|%s\n' "$(date +%s)" "$phase" "$rc" > "$failure_partial"
      mv -f -- "$failure_partial" "$root/last-failure"
    else
      printf 'BACKUP|failure-marker-skipped|reason=backup-root-unavailable|phase=%s|exit=%s\n' "$phase" "$rc" >&2
    fi
    printf 'BACKUP|FAILED|phase=%s|exit=%s\n' "$phase" "$rc" >&2
  fi
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
inventory=$(psql "${conn[@]}" -d "$POSTGRES_DB" -X -At -v ON_ERROR_STOP=1 -c 'SELECT datname FROM pg_database WHERE NOT datistemplate AND datallowconn ORDER BY datname')
[[ -n "$inventory" ]] || { echo 'BACKUP|empty-inventory' >&2; exit 1; }
mapfile -t databases <<< "$inventory"
for db in "${databases[@]}"; do
  [[ "$db" =~ ^[A-Za-z0-9_-]+$ ]] || { echo 'BACKUP|unsupported-database-filename' >&2; exit 1; }
done
stamp=$(date +%d-%B-%Y)
directory="$root/$(date +%Y)/$(date +%B)"
phase=globals
pg_dumpall "${conn[@]}" --globals-only > "$stage/globals.sql"
test -s "$stage/globals.sql"
for db in "${databases[@]}"; do
  phase="dump:$db"
  file="PG_$db.$stamp.dmp"
  pg_dump "${conn[@]}" -Fc -d "$db" > "$stage/$file"
  test -s "$stage/$file"
  phase="validate:$db"
  pg_restore --list "$stage/$file" > /dev/null
done
phase=publish
mkdir -p "$directory"
for db in "${databases[@]}"; do
  file="PG_$db.$stamp.dmp"
  partial="$directory/.$file.partial"
  cp -- "$stage/$file" "$partial"
  mv -f -- "$partial" "$directory/$file"
  partial=''
  printf 'BACKUP|archive-published|db=%s|bytes=%s\n' "$db" "$(stat -c %s "$stage/$file")"
done
partial="$root/.globals.sql.partial"
cp -- "$stage/globals.sql" "$partial"
mv -f -- "$partial" "$root/globals.sql"
write_atomic "$root/last-success-count" "${#databases[@]}"
write_atomic "$root/last-success-stamp" "$stamp"
write_atomic "$root/last-success-directory" "$directory"
rm -f -- "$root/last-failure"
partial="$root/.last-success.partial"
date +%s > "$partial"
mv -f -- "$partial" "$root/last-success"
partial=''
emit_metrics >/dev/null 2>&1 || true
printf 'BACKUP|SUCCESS|databases=%s|utc=%s|offnode=requires-independent-readback\n' "${#databases[@]}" "$(date -u '+%Y-%m-%d %H:%M UTC')"
