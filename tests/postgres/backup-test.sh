#!/bin/bash
set -euo pipefail
target=${1:?backup script path required}
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
mkdir "$root/bin" "$root/backups" "$root/metrics"
printf 'fixture-only' > "$root/password"
export BACKUP_ROOT="$root/backups" BACKUP_LOCK="$root/lock" BACKUP_METRICS_FILE="$root/metrics/postgres_backup_fixture.prom" BACKUP_SERVICE_NAME=fixture BACKUP_STATUS_INTERVAL_SECONDS=300
export POSTGRES_PASS_FILE="$root/password" POSTGRES_HOST=unused POSTGRES_PORT=5432
export POSTGRES_USER=fixture POSTGRES_DB=postgres PGSSLMODE=disable BACKUP_STALE_SECONDS=108000
export PATH="$root/bin:$PATH" FIXTURE_ROOT="$root"
cat > "$root/bin/pg_dump" <<'STUB'
#!/bin/bash
printf 'pg_dump %s
' \"$*\" >> "$FIXTURE_ROOT/pg_dump.calls"
printf 'archive-data'
exit "${DUMP_RC:-0}"
STUB
cat > "$root/bin/pg_dumpall" <<'STUB'
#!/bin/bash
printf 'pg_dumpall %s
' \"$*\" >> "$FIXTURE_ROOT/pg_dumpall.calls"
printf 'globals-data'
exit "${GLOBALS_RC:-0}"
STUB
cat > "$root/bin/psql" <<'STUB'
#!/bin/bash
printf 'psql %s
' \"$*\" >> "$FIXTURE_ROOT/psql.calls"
printf 'fixture\npostgres\n'
exit "${INVENTORY_RC:-0}"
STUB
cat > "$root/bin/pg_restore" <<'STUB'
#!/bin/bash
exit "${RESTORE_RC:-0}"
STUB
cat > "$root/bin/crontab" <<'STUB'
#!/bin/bash
cat > "$FIXTURE_ROOT/crontab.fixture"
STUB
cat > "$root/bin/cron" <<'STUB'
#!/bin/bash
[ "${1:-}" = "-f" ] || exit 2
trap 'exit 143' TERM
while true; do sleep 1; done
STUB
cat > "$root/bin/stat" <<'STUB'
#!/bin/bash
if [[ "${STAT_ROOT_FAIL:-0}" = 1 && "${1:-}" = "${BACKUP_ROOT:-}" ]]; then
  exit 70
fi
PATH=/usr/bin:/bin exec stat "$@"
STUB
cat > "$root/bin/find" <<'STUB'
#!/bin/bash
if [[ "${FIND_ROOT_FAIL:-0}" = 1 && "${1:-}" = "${BACKUP_ROOT:-}" ]]; then
  shift
  for arg in "$@"; do
    [[ "$arg" = -maxdepth ]] && exit 70
  done
fi
PATH=/usr/bin:/bin exec find "$@"
STUB
chmod +x "$root/bin/"*
dest="$BACKUP_ROOT/$(date +%Y)/$(LC_ALL=C date +%B)"
mkdir -p "$dest"
stamp="$(LC_ALL=C date +%d-%B-%Y)"
final="$dest/PG_fixture.$stamp.dmp"
for failure in DUMP_RC GLOBALS_RC INVENTORY_RC RESTORE_RC; do
 printf 'previous-valid' > "$final"
 printf 'previous-globals' > "$BACKUP_ROOT/globals.sql"
 if env "$failure=23" bash "$target" run > "$root/output" 2>&1; then
   printf 'FAIL|%s|failure-returned-success\n' "$failure"; exit 1
 fi
 [ "$(cat "$final")" = previous-valid ] || { echo "FAIL|$failure|archive-overwritten"; exit 1; }
 [ "$(cat "$BACKUP_ROOT/globals.sql")" = previous-globals ] || { echo "FAIL|$failure|globals-overwritten"; exit 1; }
 [ ! -e "$BACKUP_ROOT/last-success" ] || { echo "FAIL|$failure|false-success-marker"; exit 1; }
 [ -s "$BACKUP_ROOT/last-failure" ] || { echo "FAIL|$failure|missing-failure-marker"; exit 1; }
 printf 'PASS|%s|nonzero-and-previous-artifacts-preserved\n' "$failure"
 rm -f "$BACKUP_ROOT/last-failure" "$BACKUP_ROOT/last-attempt"
done
exec 9> "$BACKUP_LOCK"
flock -n 9
if bash "$target" run > "$root/output" 2>&1; then echo 'FAIL|overlap-accepted'; exit 1; fi
flock -u 9
bash "$target" run > "$root/output" 2>&1
[ "$(cat "$final")" = archive-data ]
[ "$(cat "$BACKUP_ROOT/globals.sql")" = globals-data ]
[ -s "$BACKUP_ROOT/last-success" ]
[ -s "$BACKUP_ROOT/last-success-count" ]
[ -s "$BACKUP_ROOT/last-success-stamp" ]
[ -s "$BACKUP_ROOT/last-success-directory" ]
[ -s "$dest/PG_postgres.$stamp.dmp" ]
echo 'PASS|success|all-databases-globals-marker-and-status-metadata'

snapshot_dir="$root/observation-snapshot"
mkdir -p "$snapshot_dir"
find "$BACKUP_ROOT" -type f -printf '%P\0' | sort -z | while IFS= read -r -d '' rel; do
  mkdir -p "$snapshot_dir/$(dirname "$rel")"
  cp -p "$BACKUP_ROOT/$rel" "$snapshot_dir/$rel"
done
before_lock_state=missing
if [[ -e "$BACKUP_LOCK" ]]; then
  before_lock_state=$(stat -c '%F:%i:%Y:%s' "$BACKUP_LOCK")
fi
before_attempt=$(cat "$BACKUP_ROOT/last-attempt")
before_success=$(cat "$BACKUP_ROOT/last-success")
before_archive=$(cat "$final")
rm -f "$root/psql.calls" "$root/pg_dump.calls" "$root/pg_dumpall.calls"
bash "$target" status >/dev/null
if [[ -e "$root/psql.calls" || -e "$root/pg_dump.calls" || -e "$root/pg_dumpall.calls" ]]; then
  echo 'FAIL|status-observation-invoked-backup-tools'
  exit 1
fi
[[ "$(cat "$BACKUP_ROOT/last-attempt")" = "$before_attempt" ]]
[[ "$(cat "$BACKUP_ROOT/last-success")" = "$before_success" ]]
[[ "$(cat "$final")" = "$before_archive" ]]
after_status_lock_state=missing
if [[ -e "$BACKUP_LOCK" ]]; then
  after_status_lock_state=$(stat -c '%F:%i:%Y:%s' "$BACKUP_LOCK")
fi
[[ "$after_status_lock_state" = "$before_lock_state" ]]
diff -r "$snapshot_dir" "$BACKUP_ROOT" >/dev/null
echo 'PASS|status-observation-mode-no-run-no-lock-no-state-mutation'

rm -f "$root/psql.calls" "$root/pg_dump.calls" "$root/pg_dumpall.calls"
bash "$target" status-metrics >/dev/null
if [[ -e "$root/psql.calls" || -e "$root/pg_dump.calls" || -e "$root/pg_dumpall.calls" ]]; then
  echo 'FAIL|status-metrics-observation-invoked-backup-tools'
  exit 1
fi
[[ "$(cat "$BACKUP_ROOT/last-attempt")" = "$before_attempt" ]]
[[ "$(cat "$BACKUP_ROOT/last-success")" = "$before_success" ]]
[[ "$(cat "$final")" = "$before_archive" ]]
after_metrics_lock_state=missing
if [[ -e "$BACKUP_LOCK" ]]; then
  after_metrics_lock_state=$(stat -c '%F:%i:%Y:%s' "$BACKUP_LOCK")
fi
[[ "$after_metrics_lock_state" = "$before_lock_state" ]]
diff -r "$snapshot_dir" "$BACKUP_ROOT" >/dev/null
grep -Fq 'postgres_backup_status_ok{service="fixture",reason="fresh-mounted-receipt"} 1' "$BACKUP_METRICS_FILE"
echo 'PASS|status-metrics-observation-mode-no-run-no-lock-no-state-mutation'
if ! grep -Eq 'timeout .*postgres-backup[.]sh.*status-metrics|timeout .*BACKUP_SCRIPT_PATH.*status-metrics' "$target"; then
  echo 'FAIL|status-metrics-observer-unbounded'
  exit 1
fi
echo 'PASS|status-metrics-observer-bounded'
echo 'PASS|metrics-fresh-visible'

available_backup_root="$BACKUP_ROOT"
blocked_parent="$root/not-a-directory"
printf 'not-a-directory' > "$blocked_parent"
export BACKUP_ROOT="$blocked_parent/child"
if bash "$target" status > "$root/status.out" 2>&1; then echo 'FAIL|unavailable-root-status'; exit 1; fi
grep -Fq 'BACKUP|backup-root-unavailable' "$root/status.out" || { cat "$root/status.out"; exit 1; }
bash "$target" status-metrics >/dev/null
grep -Fq 'reason="backup-root-unavailable"} 0' "$BACKUP_METRICS_FILE" || { cat "$BACKUP_METRICS_FILE"; exit 1; }
echo 'PASS|status-unavailable-backup-root-rejected-and-metric-visible'
for unavailable_probe in stat find; do
  export BACKUP_ROOT="$root/mkdir-succeeds-${unavailable_probe}-fails"
  mkdir -p "$BACKUP_ROOT"
  case "$unavailable_probe" in
    stat) export STAT_ROOT_FAIL=1 FIND_ROOT_FAIL=0 ;;
    find) export STAT_ROOT_FAIL=0 FIND_ROOT_FAIL=1 ;;
  esac
  if bash "$target" status > "$root/status-${unavailable_probe}.out" 2>&1; then
    echo "FAIL|${unavailable_probe}-failure-root-status"
    exit 1
  fi
  grep -Fq 'BACKUP|backup-root-unavailable' "$root/status-${unavailable_probe}.out" || { cat "$root/status-${unavailable_probe}.out"; exit 1; }
  bash "$target" status-metrics >/dev/null
  grep -Fq 'reason="backup-root-unavailable"} 0' "$BACKUP_METRICS_FILE" || { cat "$BACKUP_METRICS_FILE"; exit 1; }
done
unset STAT_ROOT_FAIL FIND_ROOT_FAIL
export BACKUP_ROOT="$blocked_parent/child"
echo 'PASS|status-disconnected-backup-root-stat-or-find-failure-rejected-and-metric-visible'
set +e
timeout 5s env CRON_SCHEDULE='* * * * *' BACKUP_STATUS_INTERVAL_SECONDS=0 BACKUP_STATUS_TIMEOUT_SECONDS=1s BACKUP_ROOT_FAILURE_EXIT_COUNT=1 BACKUP_SCRIPT_PATH="$target" bash "$target" schedule > "$root/schedule-unavailable.out" 2>&1
schedule_rc=$?
set -e
if [[ "$schedule_rc" -eq 0 || "$schedule_rc" -eq 124 ]]; then
  cat "$root/schedule-unavailable.out"
  echo "FAIL|schedule-unavailable-root-did-not-exit|exit=$schedule_rc"
  exit 1
fi
grep -Fq 'BACKUP|scheduler-exit|reason=backup-root-unavailable' "$root/schedule-unavailable.out" || { cat "$root/schedule-unavailable.out"; exit 1; }
echo 'PASS|schedule-unavailable-backup-root-exits-scheduler'
export BACKUP_ROOT="$available_backup_root"

rm -f "$BACKUP_ROOT/last-success"
if bash "$target" status > "$root/status.out" 2>&1; then echo 'FAIL|no-receipt-status'; exit 1; fi
grep -Fq 'BACKUP|no-success-receipt' "$root/status.out"
bash "$target" status-metrics >/dev/null
grep -Fq 'reason="no-success-receipt"} 0' "$BACKUP_METRICS_FILE" || { cat "$BACKUP_METRICS_FILE"; exit 1; }
echo 'PASS|status-no-success-receipt-rejected-and-metric-visible'
echo 1 > "$BACKUP_ROOT/last-success"
if bash "$target" status > "$root/status.out" 2>&1; then echo 'FAIL|stale-status'; exit 1; fi
grep -Fq 'BACKUP|stale' "$root/status.out"
bash "$target" status-metrics >/dev/null
grep -Fq 'reason="stale"} 0' "$BACKUP_METRICS_FILE" || { cat "$BACKUP_METRICS_FILE"; exit 1; }
echo 'PASS|status-stale-rejected-and-metric-visible'
now=$(date +%s)
echo "$now" > "$BACKUP_ROOT/last-success"
printf '%s|dump:fixture|23\n' "$now" > "$BACKUP_ROOT/last-failure"
if bash "$target" status > "$root/status.out" 2>&1; then echo 'FAIL|failed-same-second-status'; exit 1; fi
grep -Fq 'BACKUP|failed-last-attempt' "$root/status.out"
bash "$target" status-metrics >/dev/null
grep -Fq 'reason="failed-last-attempt"} 0' "$BACKUP_METRICS_FILE" || { cat "$BACKUP_METRICS_FILE"; exit 1; }
echo 'PASS|status-failed-last-attempt-same-second-rejected-and-metric-visible'
rm -f "$BACKUP_ROOT/last-failure"
rm -f "$BACKUP_ROOT/globals.sql"
if bash "$target" status > "$root/status.out" 2>&1; then echo 'FAIL|missing-globals-status'; exit 1; fi
grep -Fq 'BACKUP|storage-missing-globals' "$root/status.out"
bash "$target" status-metrics >/dev/null
grep -Fq 'reason="storage-missing-globals"} 0' "$BACKUP_METRICS_FILE" || { cat "$BACKUP_METRICS_FILE"; exit 1; }
echo 'PASS|status-missing-globals-rejected-and-metric-visible'
printf 'globals-data' > "$BACKUP_ROOT/globals.sql"
echo 3 > "$BACKUP_ROOT/last-success-count"
if bash "$target" status > "$root/status.out" 2>&1; then echo 'FAIL|missing-archives-status'; exit 1; fi
grep -Fq 'BACKUP|storage-missing-archives' "$root/status.out"
bash "$target" status-metrics >/dev/null
grep -Fq 'reason="storage-missing-archives"} 0' "$BACKUP_METRICS_FILE" || { cat "$BACKUP_METRICS_FILE"; exit 1; }
echo 'PASS|status-missing-archives-rejected-and-metric-visible'
if bash "$target" invalid; then echo 'FAIL|invalid-mode'; exit 1; fi
echo 'PASS|invalid-mode-rejected'
