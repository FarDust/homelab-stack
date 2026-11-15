# Thin compatibility entry points; policy and observations live in node_retention.reporting.
lanes_report_stale_once() {
  local key="${LANES_ID:-missing}:${LANES_REPORT_START_EPOCH:-missing}"
  [ "${_LANES_REPORT_RUN_KEY:-}" != "$key" ] || return "${_LANES_REPORT_RUN_RC:-2}"
  _LANES_REPORT_RUN_KEY=$key
  case "${LANES_REPORT_START_EPOCH:-}" in ''|*[!0-9]*) echo "gc_report_status=unknown missing admission epoch" >&2; return 2 ;; esac
  case "${LANES_REPORT_EXPECTED_S:-}" in ''|*[!0-9]*) echo "gc_report_status=unknown missing admission duration" >&2; return 2 ;; esac
  local rc now remaining
  now=$(date +%s); remaining=$(( LANES_REPORT_START_EPOCH + LANES_REPORT_EXPECTED_S - now - 2 ))
  [ "$remaining" -gt 0 ] || { echo "gc_report_status=unknown original job budget exhausted" >&2; return 2; }
  [ "$remaining" -le 4 ] || remaining=4
  if NODE_RETENTION_REPORT_JOB_ID="${LANES_ID:-}" \
     NODE_RETENTION_REPORT_OWNER="${LANES_WHO:-}" \
     NODE_RETENTION_REPORT_HOST="$(hostname)" \
     NODE_RETENTION_REPORT_PID="${LANES_RUN:-}" \
     NODE_RETENTION_REPORT_JOBS_ROOT="${LANES_JOBS_ROOT:-}" \
     NODE_RETENTION_REPORT_LEDGER="${LANES_LEDGER:-}" \
     NODE_RETENTION_REPORT_PUBLISHER="${LANES_LEDGER_BIN:-}" \
     NODE_RETENTION_REPORT_STARTED_EPOCH="${LANES_REPORT_START_EPOCH:-}" \
     NODE_RETENTION_REPORT_EXPECTED_SECONDS="${LANES_REPORT_EXPECTED_S:-}" \
     NODE_RETENTION_REPORT_PHASE_DEADLINE_EPOCH="$(( now + remaining ))" \
     NODE_RETENTION_REPORT_STALE_HOURS="${LANES_GC_REPORT_AGE_H:-6}" \
     /usr/bin/timeout --signal=TERM --kill-after=1 "$remaining" "${LANES_REPORT_EXECUTABLE:?versioned report executable required}" >&2; then
    rc=0
  else
    rc=$?
  fi
  [ "$rc" -eq 0 ] || echo "gc_report_status=unknown_or_partial exit=$rc" >&2
  _LANES_REPORT_RUN_RC=$rc
  return "$rc"
}
