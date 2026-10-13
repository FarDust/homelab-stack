#!/bin/sh
# Scheduled, I/O-gated archive of the Loki data volume to the rclone-backed GCS volume.
# As decided in docs/adr/loki_gcs_durability_adr.md
#
# Modes:
#   serve                       run busybox crond with the schedule in LOKI_BACKUP_SCHEDULE
#   run                         one backup now (also what crond calls)
#   restore <archive> <target>  extract an archive into an empty target directory
set -eu

SRC=${LOKI_BACKUP_SOURCE:-/source}
DEST=${LOKI_BACKUP_DEST:-/dest}
KEEP=${LOKI_BACKUP_KEEP:-6}
METRICS_FILE=${LOKI_BACKUP_METRICS_FILE:-/metrics/loki_backup.prom}
PSI_FILE=${LOKI_BACKUP_PSI_FILE:-/proc/pressure/io}
PSI_MAX=${LOKI_BACKUP_PSI_MAX_AVG60:-75}
PSI_DEADLINE=${LOKI_BACKUP_PSI_DEADLINE_SECONDS:-5400}
MIN_SOURCE_KB=${LOKI_BACKUP_MIN_SOURCE_KB:-1024}
ENV_FILE=/run/loki-backup.env

log() { printf '%s loki-backup: %s\n' "$(date -u +%FT%TZ)" "$*"; }
fail() { log "ERROR: $*"; emit_metrics 0 0 0; exit 1; }

emit_metrics() {
  ok=$1; bytes=$2; secs=$3
  mkdir -p "$(dirname "$METRICS_FILE")" 2>/dev/null || return 0
  tmp="$METRICS_FILE.partial"
  now=$(date +%s)
  prev=0
  if [ -f "$METRICS_FILE" ]; then
    prev=$(awk '/^loki_backup_last_success_timestamp_seconds /{print $2}' "$METRICS_FILE" 2>/dev/null || echo 0)
    [ -n "$prev" ] || prev=0
  fi
  success_ts=$prev
  [ "$ok" = 1 ] && success_ts=$now
  {
    echo '# HELP loki_backup_last_run_success 1 when the last backup run succeeded.'
    echo '# TYPE loki_backup_last_run_success gauge'
    echo "loki_backup_last_run_success $ok"
    echo '# HELP loki_backup_last_success_timestamp_seconds Unix time of the last successful archive written to the GCS-backed mount.'
    echo '# TYPE loki_backup_last_success_timestamp_seconds gauge'
    echo "loki_backup_last_success_timestamp_seconds $success_ts"
    echo '# HELP loki_backup_last_archive_bytes Size of the last successful archive.'
    echo '# TYPE loki_backup_last_archive_bytes gauge'
    echo "loki_backup_last_archive_bytes $bytes"
    echo '# HELP loki_backup_last_duration_seconds Duration of the last run.'
    echo '# TYPE loki_backup_last_duration_seconds gauge'
    echo "loki_backup_last_duration_seconds $secs"
  } > "$tmp" 2>/dev/null && mv -f "$tmp" "$METRICS_FILE" 2>/dev/null || true
}

# Wait for the observed condition (host I/O pressure below threshold); the deadline is only a failure bound.
wait_for_io_headroom() {
  [ -r "$PSI_FILE" ] || { log "PSI unavailable at $PSI_FILE; continuing without gate"; return 0; }
  start=$(date +%s)
  while :; do
    avg60=$(awk '/^some /{for(i=1;i<=NF;i++) if($i ~ /^avg60=/){sub("avg60=","",$i); print int($i)}}' "$PSI_FILE")
    if [ "${avg60:-0}" -le "$PSI_MAX" ]; then
      log "io pressure some avg60=${avg60:-0} <= $PSI_MAX, proceeding"
      return 0
    fi
    now=$(date +%s)
    [ $((now - start)) -lt "$PSI_DEADLINE" ] || fail "io pressure stayed above $PSI_MAX (avg60=$avg60) for ${PSI_DEADLINE}s"
    sleep 30
  done
}

run_backup() {
  started=$(date +%s)
  # A named local volume is created empty on whichever node runs the task; refuse to archive nothing.
  [ -d "$SRC/chunks" ] && [ -d "$SRC/index" ] || fail "source $SRC has no chunks/index directories (wrong node or empty volume)"
  src_kb=$(du -sk "$SRC/chunks" "$SRC/index" | awk '{s+=$1} END{print s+0}')
  [ "$src_kb" -ge "$MIN_SOURCE_KB" ] || fail "source holds only ${src_kb} KiB; refusing to archive a near-empty volume"
  [ -d "$DEST" ] && [ -w "$DEST" ] || fail "destination $DEST is not a writable directory"
  wait_for_io_headroom

  ts=$(date -u +%Y%m%dT%H%M%SZ)
  partial="$DEST/.partial-loki-$ts.tar"
  final="$DEST/loki-$ts.tar"
  log "archiving ${src_kb} KiB (chunks, index, compactor) to $final"
  set +e
  nice -n 19 ionice -c3 tar -C "$SRC" -cf "$partial" chunks index compactor
  rc=$?
  set -e
  # busybox tar exits 1 when a file changed while it was read; chunks are write-once, tolerate only that.
  if [ "$rc" -ne 0 ] && [ "$rc" -ne 1 ]; then
    rm -f "$partial"
    fail "tar exited $rc"
  fi
  # Check the archive is readable end to end and holds index and chunk members before publishing it.
  members=$(tar -tf "$partial" | awk -F/ '$1=="chunks"||$1=="index"{n++} END{print n+0}')
  [ "$members" -gt 0 ] || { rm -f "$partial"; fail "archive $partial has no chunks/index members"; }
  bytes=$(stat -c %s "$partial")
  mv "$partial" "$final"
  log "wrote $final bytes=$bytes members=$members tar_rc=$rc"

  # Retention: keep the newest KEEP archives; the bucket also keeps versions and a 7 day soft-delete window.
  count=0
  for f in $(ls -1 "$DEST"/loki-*.tar 2>/dev/null | sort -r); do
    count=$((count + 1))
    if [ "$count" -gt "$KEEP" ]; then
      log "pruning $f"
      rm -f "$f"
    fi
  done
  emit_metrics 1 "$bytes" $(( $(date +%s) - started ))
}

restore_backup() {
  archive=${1:?usage: restore <archive> <target>}
  target=${2:?usage: restore <archive> <target>}
  [ -f "$archive" ] || fail "archive $archive not found"
  mkdir -p "$target"
  [ -z "$(ls -A "$target")" ] || fail "target $target is not empty"
  tar -C "$target" -xf "$archive"
  log "restored $archive into $target"
}

case "${1:-}" in
  serve)
    schedule=${LOKI_BACKUP_SCHEDULE:?LOKI_BACKUP_SCHEDULE is required}
    : > "$ENV_FILE"
    for k in LOKI_BACKUP_SOURCE LOKI_BACKUP_DEST LOKI_BACKUP_KEEP LOKI_BACKUP_METRICS_FILE LOKI_BACKUP_PSI_MAX_AVG60 LOKI_BACKUP_PSI_DEADLINE_SECONDS LOKI_BACKUP_MIN_SOURCE_KB; do
      eval "v=\${$k:-}"
      [ -z "$v" ] || printf 'export %s=%s\n' "$k" "$v" >> "$ENV_FILE"
    done
    crontab_dir=/etc/crontabs
    mkdir -p "$crontab_dir"
    printf '%s . %s; /bin/sh /scripts/loki-backup.sh run > /proc/1/fd/1 2>&1\n' "$schedule" "$ENV_FILE" > "$crontab_dir/$(id -un)"
    log "serving schedule: $schedule"
    exec crond -f -l 8 -L /dev/stdout
    ;;
  run) run_backup ;;
  restore) shift; restore_backup "$@" ;;
  *) echo "usage: $0 {serve|run|restore <archive> <target>}" >&2; exit 2 ;;
esac
