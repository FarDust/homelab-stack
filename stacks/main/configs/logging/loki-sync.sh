#!/bin/sh
# Copy the Loki local filesystem store (chunks, TSDB index, WAL) to a WebDAV replica and to GCS.
# Immutable chunk/index files are only ever copied (--ignore-existing); only the guarded prune deletes.
#
# Modes:
#   serve                              run busybox crond with the schedules from LOKI_SYNC_SCHEDULE_* env
#   run replica [incr|full]            copy to the WebDAV replica (default incr: --max-age window)
#   run gcs [incr|full]                copy chunks (+chunks/index) to GCS, copy-only, never deletes
#   run prune [replica|gcs]            guarded delete of files that vanished from the source (gcs needs LOKI_SYNC_ALLOW_GCS_PRUNE=1)
#   run check [replica|gcs]           rclone check --one-way --size-only for replica and gcs, emits missing/differ counts
#   restore <replica|gcs> <target>     copy a destination back into an EMPTY target dir (LOKI_SYNC_RESTORE_MODE=mirror for failback)
set -eu

SRC=${LOKI_SYNC_SOURCE:-/source}
MARKER=${LOKI_SYNC_MARKER:-$SRC/.loki-store-initialized}
METRICS_DIR=${LOKI_SYNC_METRICS_DIR:-/metrics}
METRICS_FILE=${LOKI_SYNC_METRICS_FILE:-$METRICS_DIR/loki_sync.prom}
STATE_DIR=${LOKI_SYNC_STATE_DIR:-$METRICS_DIR/.loki_sync_state}
PSI_FILE=${LOKI_SYNC_PSI_FILE:-/proc/pressure/io}
PSI_MAX=${LOKI_SYNC_PSI_MAX_AVG60:-40}
PSI_DEADLINE_INCR=${LOKI_SYNC_PSI_DEADLINE_INCR_SECONDS:-120}
PSI_DEADLINE_FULL=${LOKI_SYNC_PSI_DEADLINE_FULL_SECONDS:-5400}
MAX_AGE=${LOKI_SYNC_MAX_AGE:-3h}
MIN_AGE=${LOKI_SYNC_MIN_AGE:-1m}
CHECK_MIN_AGE=${LOKI_SYNC_CHECK_MIN_AGE:-10m}
BWLIMIT_INCR=${LOKI_SYNC_BWLIMIT_INCR:-8M}
BWLIMIT_FULL=${LOKI_SYNC_BWLIMIT_FULL:-4M}
TRANSFERS=${LOKI_SYNC_TRANSFERS:-2}
CHECKERS=${LOKI_SYNC_CHECKERS:-4}
BESTEFFORT_DIRS=${LOKI_SYNC_BESTEFFORT_DIRS:-wal index compactor}
BESTEFFORT_MAX_DELETE=${LOKI_SYNC_BESTEFFORT_MAX_DELETE:-500}
MIN_CHUNKS=${LOKI_SYNC_MIN_CHUNKS:-1000}
PRUNE_MAX_DELETE=${LOKI_SYNC_PRUNE_MAX_DELETE:-2000}
REPLICA_URL=${LOKI_SYNC_REPLICA_URL:-http://loki-replica:8080}
REPLICA_USER=${LOKI_SYNC_REPLICA_USER:-loki}
REPLICA_PASS_FILE=${LOKI_SYNC_REPLICA_PASS_FILE:-/run/secrets/loki_replica_pass}
GCS_KEY_FILE=${LOKI_SYNC_GCS_KEY_FILE:-/run/secrets/loki_gcs_sa_key}
GCS_SCOPE=${LOKI_SYNC_GCS_BUCKET:?LOKI_SYNC_GCS_BUCKET must name the artifacts bucket}/loki/cluster/
GCS_PATH=${LOKI_SYNC_GCS_PATH:-${GCS_SCOPE}backup-store}
ENV_FILE=/run/loki-sync.env
WORK=${LOKI_SYNC_WORK_DIR:-/tmp/loki-sync}

T=none
M=none
PRIO=""
STARTED=$(date +%s)
log() { printf '%s loki-sync[%s/%s]: %s\n' "$(date -u +%FT%TZ)" "$T" "$M" "$*"; }
fail() {
  log "ERROR: $*"
  # A failure has to be visible to alerting: record ok=0 for the target/mode that was running.
  [ "$T" = none ] || write_state 0 "$(( $(date +%s) - STARTED ))" 0 0
  exit 1
}

mkdir -p "$WORK" "$STATE_DIR" 2>/dev/null || true

export RCLONE_CONFIG=${RCLONE_CONFIG:-/dev/null}

# ---- state and Prometheus textfile metrics (atomic rewrite) -------------------------------------------------
state_file() { echo "$STATE_DIR/${1}_${2}.state"; }
prev_value() { # file key default
  v=""
  [ ! -f "$1" ] || v=$(awk -F= -v k="$2" '$1==k{print $2}' "$1")
  echo "${v:-$3}"
}
# write_state ok duration bytes files [missing differ deleted]; counters accumulate, gauges not given keep their last value.
write_state() {
  ok=$1; dur=$2; bytes=$3; files=$4; missing=${5:-}; differ=${6:-}; deleted=${7:-}
  f=$(state_file "$T" "$M")
  now=$(date +%s)
  last=$(prev_value "$f" last_success 0)
  [ "$ok" != 1 ] || last=$now
  ws_b=$(( $(prev_value "$f" bytes_total 0) + bytes ))
  ws_n=$(( $(prev_value "$f" files_total 0) + files ))
  ws_s=$(prev_value "$f" skipped_total 0)
  [ -n "$missing" ] || missing=$(prev_value "$f" missing -1)
  [ -n "$differ" ] || differ=$(prev_value "$f" differ -1)
  [ -n "$deleted" ] || deleted=$(prev_value "$f" deleted 0)
  { echo "ok=$ok"; echo "last_success=$last"; echo "duration=$dur"; echo "bytes_total=$ws_b"; echo "files_total=$ws_n"
    echo "skipped_total=$ws_s"; echo "missing=$missing"; echo "differ=$differ"; echo "deleted=$deleted"; } > "$f.partial"
  mv -f "$f.partial" "$f"
  render_metrics
}
bump_skipped() {
  f=$(state_file "$T" "$M")
  [ -f "$f" ] || printf 'ok=1\nlast_success=0\nduration=0\nbytes_total=0\nfiles_total=0\nskipped_total=0\nmissing=-1\ndiffer=-1\ndeleted=0\n' > "$f"
  sk=$(( $(prev_value "$f" skipped_total 0) + 1 ))
  sed "s/^skipped_total=.*/skipped_total=$sk/" "$f" > "$f.partial" && mv -f "$f.partial" "$f"
  render_metrics
}
render_metrics() {
  set -- "$STATE_DIR"/*.state
  [ -f "$1" ] || return 0
  tmp="$METRICS_FILE.partial"
  awk '
    FNR==1 { n=FILENAME; sub(".*/","",n); sub("[.]state$","",n); i=index(n,"_"); nk++; tg[nk]=substr(n,1,i-1); md[nk]=substr(n,i+1) }
    { split($0,kv,"="); val[nk,kv[1]]=kv[2] }
    function fam(name,key,type,help,only,   i) {
      printf "# HELP %s %s\n# TYPE %s %s\n", name, help, name, type
      for (i=1;i<=nk;i++) if (((i,key) in val) && (only=="" || md[i]==only)) printf "%s{target=\"%s\",mode=\"%s\"} %s\n", name, tg[i], md[i], val[i,key]
    }
    END {
      fam("loki_sync_last_run_success","ok","gauge","1 when the last run of this target and mode succeeded.")
      fam("loki_sync_last_success_timestamp_seconds","last_success","gauge","Unix time of the last successful run (0 when none yet).")
      fam("loki_sync_last_duration_seconds","duration","gauge","Duration of the last run.")
      fam("loki_sync_bytes_total","bytes_total","counter","Bytes transferred since the state was created.")
      fam("loki_sync_files_total","files_total","counter","Files transferred since the state was created.")
      fam("loki_sync_skipped_total","skipped_total","counter","Runs skipped because another run held the lock or I/O pressure stayed high.")
      fam("loki_sync_missing_files","missing","gauge","Source files missing on the destination at the last check (-1 never checked).","check")
      fam("loki_sync_differ_files","differ","gauge","Files whose size differs between source and destination at the last check (-1 never checked).","check")
      fam("loki_sync_deleted_files","deleted","gauge","Files deleted from the destination by the last prune run.","prune")
    }' "$@" > "$tmp" && mv -f "$tmp" "$METRICS_FILE" || log "WARN: could not write $METRICS_FILE"
}

# ---- guards --------------------------------------------------------------------------------------------------
# Wait for the observed condition (local I/O pressure below the threshold); the deadline is only a skip bound.
wait_for_io_headroom() {
  deadline=$1
  [ -r "$PSI_FILE" ] || { log "PSI unavailable at $PSI_FILE; continuing without gate"; return 0; }
  start=$(date +%s)
  while :; do
    avg60=$(awk '/^some /{for(i=1;i<=NF;i++) if($i ~ /^avg60=/){sub("avg60=","",$i); print int($i)}}' "$PSI_FILE")
    if [ "${avg60:-0}" -le "$PSI_MAX" ]; then
      log "io pressure some avg60=${avg60:-0} <= $PSI_MAX, proceeding"
      return 0
    fi
    [ $(( $(date +%s) - start )) -lt "$deadline" ] || return 1
    sleep 15
  done
}
# The bind mount can come up as an empty directory on a wrong node; the marker proves this is the real store.
require_source() {
  [ -d "$SRC" ] || fail "source $SRC is not a directory (bind mount missing)"
  [ -f "$MARKER" ] || fail "marker $MARKER missing; refusing to sync an unverified source"
  [ -d "$SRC/chunks" ] || fail "source $SRC has no chunks directory"
}
take_lock() { # one run per target at a time; overlapping runs would race on --ignore-existing uploads
  exec 9>"$WORK/$T.lock"
  flock -n 9 || { log "another $T run holds the lock; skipping"; bump_skipped; exit 0; }
  : > "$WORK/rclone-$T-$M.log"
}

# ---- rclone remotes (credentials only through files/env inside the container, never argv) -------------------
use_replica() {
  [ -r "$REPLICA_PASS_FILE" ] || fail "replica password file $REPLICA_PASS_FILE unreadable"
  RCLONE_WEBDAV_URL=$REPLICA_URL
  RCLONE_WEBDAV_VENDOR=other
  RCLONE_WEBDAV_USER=$REPLICA_USER
  RCLONE_WEBDAV_PASS=$(printf %s "$(cat "$REPLICA_PASS_FILE")" | rclone obscure -) || fail "could not obscure replica password"
  export RCLONE_WEBDAV_URL RCLONE_WEBDAV_VENDOR RCLONE_WEBDAV_USER RCLONE_WEBDAV_PASS
  DST=":webdav:"
}
use_gcs() {
  [ -r "$GCS_KEY_FILE" ] || fail "GCS key file $GCS_KEY_FILE unreadable"
  # The identity only reaches loki/cluster/; every call must stay inside it and cannot check the bucket.
  case "$GCS_PATH" in *..*) fail "GCS path $GCS_PATH contains .." ;; esac
  case "$GCS_PATH" in "$GCS_SCOPE"?*) ;; *) fail "GCS path $GCS_PATH is outside $GCS_SCOPE" ;; esac
  RCLONE_GCS_SERVICE_ACCOUNT_FILE=$GCS_KEY_FILE
  RCLONE_GCS_NO_CHECK_BUCKET=true
  RCLONE_GCS_BUCKET_POLICY_ONLY=true
  export RCLONE_GCS_SERVICE_ACCOUNT_FILE RCLONE_GCS_NO_CHECK_BUCKET RCLONE_GCS_BUCKET_POLICY_ONLY
  DST=":gcs:$GCS_PATH/"
}
use_target() {
  case "$1" in
    replica) use_replica ;;
    gcs) use_gcs ;;
    *) fail "unknown target $1" ;;
  esac
}

# Run rclone (under $PRIO) with JSON logging and add its final stats to TOT_BYTES/TOT_FILES/TOT_DELETES.
TOT_BYTES=0; TOT_FILES=0; TOT_DELETES=0
rc_run() {
  log_file="$WORK/rclone-$T-$M.call"
  : > "$log_file"
  set +e
  # shellcheck disable=SC2086
  $PRIO rclone --use-json-log -v --stats 0 --log-file "$log_file" "$@"
  rc=$?
  set -e
  # Count what rclone reports per file (Copied lines carry the size; Deleted lines carry the deletion).
  rc_b=$(grep -o '"msg":"Copied[^"]*","size":[0-9]*' "$log_file" | awk -F: '{s+=$NF} END{print s+0}')
  rc_f=$(grep -c '"msg":"Copied' "$log_file" || true)
  rc_d=$(grep -c '"msg":"Deleted"' "$log_file" || true)
  TOT_BYTES=$(( TOT_BYTES + ${rc_b:-0} ))
  TOT_FILES=$(( TOT_FILES + ${rc_f:-0} ))
  TOT_DELETES=$(( TOT_DELETES + ${rc_d:-0} ))
  cat "$log_file" >> "$WORK/rclone-$T-$M.log"
  if [ "$rc" -ne 0 ]; then
    grep -E '"level":"(error|critical)"' "$log_file" | tail -5 | cut -c1-400 >&2 || true
    return "$rc"
  fi
}

# ---- copy ----------------------------------------------------------------------------------------------------
run_copy() {
  T=$1; M=${2:-incr}
  case "$M" in incr|full) ;; *) echo "mode must be incr or full" >&2; exit 2 ;; esac
  STARTED=$(date +%s)
  require_source
  take_lock
  deadline=$PSI_DEADLINE_INCR; [ "$M" != full ] || deadline=$PSI_DEADLINE_FULL
  wait_for_io_headroom "$deadline" || { log "io pressure stayed above $PSI_MAX for ${deadline}s; skipping this run"; bump_skipped; exit 0; }
  use_target "$T"
  if [ "$M" = full ]; then
    PRIO="nice -n 19 ionice -c3"; flags="--bwlimit $BWLIMIT_FULL"
  else
    PRIO="nice -n 10 ionice -c2 -n7"; flags="--no-traverse --max-age $MAX_AGE --bwlimit $BWLIMIT_INCR"
  fi
  # Chunks first, then the index objects, so the destination never holds an index that points at missing chunks.
  # --min-age keeps files that Loki may still be writing out of the copy; --ignore-existing never overwrites.
  # shellcheck disable=SC2086
  rc_run copy "$SRC/chunks" "${DST}chunks" --exclude '/index/**' --ignore-existing --min-age "$MIN_AGE" \
    --transfers "$TRANSFERS" --checkers "$CHECKERS" $flags || fail "chunk copy failed"
  if [ -d "$SRC/chunks/index" ]; then
    # shellcheck disable=SC2086
    rc_run copy "$SRC/chunks/index" "${DST}chunks/index" --ignore-existing --min-age "$MIN_AGE" \
      --transfers "$TRANSFERS" --checkers "$CHECKERS" $flags || fail "index copy failed"
  fi
  rc_run copyto "$MARKER" "${DST}$(basename "$MARKER")" --ignore-existing || fail "marker copy failed"
  if [ "$T" = replica ]; then
    # WAL, active index and compactor state are small and mutable: mirror them, best effort (consistency not guaranteed).
    for d in $BESTEFFORT_DIRS; do
      [ -d "$SRC/$d" ] || continue
      rc_run sync "$SRC/$d" "${DST}$d" --max-delete "$BESTEFFORT_MAX_DELETE" --transfers "$TRANSFERS" --checkers "$CHECKERS" \
        --bwlimit "$BWLIMIT_INCR" || log "WARN: best-effort sync of $d failed (non-fatal)"
    done
  fi
  dur=$(( $(date +%s) - STARTED ))
  write_state 1 "$dur" "$TOT_BYTES" "$TOT_FILES"
  log "ok bytes=$TOT_BYTES files=$TOT_FILES duration=${dur}s"
}

# ---- prune (the only deleting path) -------------------------------------------------------------------------
run_prune() {
  T=${1:-replica}; M=prune
  STARTED=$(date +%s)
  case "$T" in replica|gcs) ;; *) echo "prune target must be replica or gcs" >&2; exit 2 ;; esac
  if [ "$T" = gcs ] && [ "${LOKI_SYNC_ALLOW_GCS_PRUNE:-0}" != 1 ]; then fail "GCS is copy-only; set LOKI_SYNC_ALLOW_GCS_PRUNE=1 for a deliberate prune"; fi
  require_source
  take_lock
  chunks=$(find "$SRC/chunks" -path "$SRC/chunks/index" -prune -o -type f -print | wc -l)
  [ "$chunks" -ge "$MIN_CHUNKS" ] || fail "source holds only $chunks chunk files (< $MIN_CHUNKS); refusing to prune"
  wait_for_io_headroom "$PSI_DEADLINE_FULL" || { log "io pressure stayed high; skipping prune"; bump_skipped; exit 0; }
  use_target "$T"
  PRIO="nice -n 19 ionice -c3"
  # Pre-flight: files that exist on the destination but not in the source = what sync would delete.
  extra="$WORK/prune-extra-$T.lst"; : > "$extra"
  set +e
  $PRIO rclone check "${DST}chunks" "$SRC/chunks" --one-way --size-only --missing-on-dst "$extra" \
    --min-age "$CHECK_MIN_AGE" --checkers "$CHECKERS" 2> "$WORK/prune-check.err"
  rc=$?
  set -e
  if [ "$rc" -ne 0 ] && ! grep -q 'differences found' "$WORK/prune-check.err"; then
    head -5 "$WORK/prune-check.err" | cut -c1-300 >&2; fail "prune pre-flight check failed (rc=$rc)"
  fi
  n=$(wc -l < "$extra")
  log "prune pre-flight: $n files would be deleted (cap $PRUNE_MAX_DELETE), source chunks=$chunks"
  [ "$n" -le "$PRUNE_MAX_DELETE" ] || fail "prune would delete $n files (> $PRUNE_MAX_DELETE); source looks damaged, refusing"
  if [ "$n" -gt 0 ]; then
    # --ignore-existing: sync may only delete, never overwrite; --max-delete is the second line of defence.
    rc_run sync "$SRC/chunks" "${DST}chunks" --ignore-existing --delete-after --max-delete "$PRUNE_MAX_DELETE" \
      --min-age "$CHECK_MIN_AGE" --transfers "$TRANSFERS" --checkers "$CHECKERS" || fail "prune sync failed"
  fi
  write_state 1 "$(( $(date +%s) - STARTED ))" 0 0 "" "" "$n"
  log "ok deleted=$n (rclone reported $TOT_DELETES)"
}

# ---- check ---------------------------------------------------------------------------------------------------
check_one() { # target; runs in a subshell so a failure only marks this target
  T=$1; M=check
  STARTED=$(date +%s)
  use_target "$T"
  PRIO="nice -n 19 ionice -c3"
  miss="$WORK/check-missing-$T.lst"; diff="$WORK/check-differ-$T.lst"
  srcl="$WORK/check-src-$T.lst"; dstl="$WORK/check-dst-$T.lst"
  # Compare two listings (size|path) instead of rclone check: the replica keeps upload time as mtime (WebDAV), so an
  # age filter must apply to the source side only, and files younger than CHECK_MIN_AGE are not yet due for copying.
  # Missing files are healed once (copied) and the comparison repeats, so the metric reports what is still missing.
  attempt=1
  while :; do
    : > "$miss"; : > "$diff"
    set +e
    $PRIO rclone lsf -R --files-only --format sp --separator '|' --min-age "$CHECK_MIN_AGE" "$SRC/chunks" 2> "$WORK/check-$T.err" | LC_ALL=C sort -t'|' -k2 > "$srcl"
    rs=$?
    $PRIO rclone lsf -R --files-only --format sp --separator '|' "${DST}chunks" 2>> "$WORK/check-$T.err" | LC_ALL=C sort -t'|' -k2 > "$dstl"
    rd=$?
    set -e
    if [ "$rs" -ne 0 ] || [ "$rd" -ne 0 ] || [ ! -s "$srcl" ] || [ ! -s "$dstl" ]; then
      head -3 "$WORK/check-$T.err" | cut -c1-300 >&2; fail "check against $T could not list source or destination; result discarded"
    fi
    awk -F'|' -v miss="$miss" -v diff="$diff" 'NR==FNR{d[$2]=$1; next} !($2 in d){print $2 > miss; next} d[$2]!=$1{print $2 > diff}' "$dstl" "$srcl"
    m=$(wc -l < "$miss")
    if [ "$m" -gt 0 ] && [ "$attempt" -eq 1 ]; then
      log "check found $m files missing on $T; copying them and checking again"
      M=check-heal
      rc_run copy "$SRC/chunks" "${DST}chunks" --files-from "$miss" --ignore-existing --min-age 1m --transfers "$TRANSFERS" --checkers "$CHECKERS" || log "heal copy reported errors"
      M=check
      attempt=2
      continue
    fi
    break
  done
  d=$(wc -l < "$diff")
  log "missing=$m differ=$d (listing comparison, files older than $CHECK_MIN_AGE, $attempt pass(es))"
  [ "$m" -eq 0 ] || { echo "first missing:"; head -5 "$miss"; }
  [ "$d" -eq 0 ] || { echo "first differing:"; head -5 "$diff"; }
  write_state 1 "$(( $(date +%s) - STARTED ))" 0 0 "$m" "$d"
}
run_check() {
  require_source
  if ! wait_for_io_headroom "$PSI_DEADLINE_FULL"; then log "io pressure stayed high; skipping check"; exit 0; fi
  rcs=0
  for t in ${1:-replica gcs}; do
    ( check_one "$t" ) || rcs=1
  done
  [ "$rcs" -eq 0 ] || exit 1
}

# ---- restore -------------------------------------------------------------------------------------------------
run_restore() {
  T=${1:?usage: restore <replica|gcs> <target>}; M=restore
  target=${2:?usage: restore <replica|gcs> <target>}
  STARTED=$(date +%s)
  use_target "$T"
  PRIO=""
  : > "$WORK/rclone-$T-$M.log"
  mkdir -p "$target"
  mode=${LOKI_SYNC_RESTORE_MODE:-empty}
  if [ "$mode" = empty ]; then
    [ -z "$(ls -A "$target")" ] || fail "target $target is not empty (set LOKI_SYNC_RESTORE_MODE=mirror for a deliberate failback)"
  fi
  # Chunks before the index objects, same as the forward path. Chunks are never deleted locally, even in mirror mode.
  rc_run copy "${DST}chunks" "$target/chunks" --exclude '/index/**' --transfers 4 --checkers 8 || fail "restore of chunks failed"
  rc_run copy "${DST}chunks/index" "$target/chunks/index" --transfers 4 --checkers 8 || log "no chunks/index on $T (continuing)"
  if [ "$T" = replica ]; then
    for d in $BESTEFFORT_DIRS; do
      rc_run sync "${DST}$d" "$target/$d" --transfers 4 --checkers 8 || log "no $d on $T (continuing)"
    done
  fi
  rc_run copyto "${DST}$(basename "$MARKER")" "$target/$(basename "$MARKER")" || log "no marker on $T (continuing)"
  # Verify: every file on the destination exists with the same size locally.
  set +e
  rclone check "${DST}chunks" "$target/chunks" --one-way --size-only 2> "$WORK/restore-check.err"
  rc=$?
  set -e
  [ "$rc" -eq 0 ] || { head -5 "$WORK/restore-check.err" | cut -c1-300 >&2; fail "restore verification failed (rc=$rc)"; }
  files=$(find "$target/chunks" -type f | wc -l)
  log "restored from $T into $target: chunk tree files=$files bytes=$TOT_BYTES; verification ok"
}

# ---- entry ---------------------------------------------------------------------------------------------------
case "${1:-}" in
  serve)
    : > "$ENV_FILE"
    for k in $(env | sed -n 's/^\(LOKI_SYNC_[A-Z_]*\)=.*/\1/p'); do
      case "$k" in LOKI_SYNC_SCHEDULE_*) continue ;; esac
      eval "v=\${$k}"
      printf "export %s='%s'\n" "$k" "$v" >> "$ENV_FILE"
    done
    dir=/etc/crontabs; mkdir -p "$dir"; : > "$dir/$(id -un)"
    add() { # schedule args...
      sch=$1; shift
      [ -n "$sch" ] || return 0
      printf '%s . %s; /bin/sh /scripts/loki-sync.sh run %s > /proc/1/fd/1 2>&1\n' "$sch" "$ENV_FILE" "$*" >> "$dir/$(id -un)"
      log "scheduled '$sch' -> run $*"
    }
    add "${LOKI_SYNC_SCHEDULE_REPLICA:-*/5 * * * *}" replica incr
    add "${LOKI_SYNC_SCHEDULE_REPLICA_FULL:-15 3 * * *}" replica full
    add "${LOKI_SYNC_SCHEDULE_PRUNE:-30 4 * * *}" prune replica
    add "${LOKI_SYNC_SCHEDULE_GCS:-7,37 * * * *}" gcs incr
    add "${LOKI_SYNC_SCHEDULE_GCS_FULL:-45 3 * * *}" gcs full
    add "${LOKI_SYNC_SCHEDULE_CHECK:-0 5 * * *}" check
    exec crond -f -l 8 -L /dev/stdout
    ;;
  run)
    case "${2:-}" in
      replica|gcs) run_copy "$2" "${3:-incr}" ;;
      prune) run_prune "${3:-replica}" ;;
      check) run_check "${3:-}" ;;
      *) echo "usage: $0 run {replica|gcs} [incr|full] | run prune [replica|gcs] | run check" >&2; exit 2 ;;
    esac
    ;;
  restore) shift; run_restore "$@" ;;
  *) echo "usage: $0 {serve|run <target> [mode]|restore <replica|gcs> <target>}" >&2; exit 2 ;;
esac
