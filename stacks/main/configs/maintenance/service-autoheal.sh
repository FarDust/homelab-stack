#!/bin/sh
set -eu

INTERVAL=${AUTOHEAL_INTERVAL:-300}
COOLDOWN_MINUTES=${AUTOHEAL_COOLDOWN:-30}
MAX_RETRIES=${AUTOHEAL_MAX_RETRIES:-3}
STATE_DIR="/state"

mkdir -p "$STATE_DIR"

log() { echo "[$(date -Iseconds)] $*"; }

cleanup_old_state() {
  find "$STATE_DIR" -name '*.retry' -mmin +1440 -delete 2>/dev/null || true
}

get_retry_count() {
  local svc="$1"
  local file="$STATE_DIR/$(echo "$svc" | tr '/' '_').retry"
  if [ -f "$file" ]; then
    cat "$file"
  else
    echo "0"
  fi
}

increment_retry() {
  local svc="$1"
  local file="$STATE_DIR/$(echo "$svc" | tr '/' '_').retry"
  local count=$(get_retry_count "$svc")
  echo $((count + 1)) > "$file"
}

clear_retry() {
  local svc="$1"
  local file="$STATE_DIR/$(echo "$svc" | tr '/' '_').retry"
  rm -f "$file" 2>/dev/null || true
}

log "Service autoheal starting (interval=${INTERVAL}s, cooldown=${COOLDOWN_MINUTES}min, max_retries=${MAX_RETRIES})"

while true; do
  cleanup_old_state

  docker service ls --format '{{.Name}} {{.Replicas}}' 2>/dev/null | while read name replicas; do
    running=$(echo "$replicas" | cut -d/ -f1)
    desired=$(echo "$replicas" | cut -d/ -f2 | cut -d' ' -f1)

    [ -z "$desired" ] && continue
    [ "$desired" = "0" ] && continue
    [ "$running" = "$desired" ] && { clear_retry "$name"; continue; }

    newest_state=$(docker service ps "$name" --format '{{.CurrentState}}' 2>/dev/null | head -1)

    case "$newest_state" in
      Running*|Starting*|Preparing*|Ready*|New*|Assigned*|Accepted*|Complete*) continue ;;
    esac

    is_old_enough=false
    if echo "$newest_state" | grep -qE '[0-9]+ hours ago|[0-9]+ days ago'; then
      is_old_enough=true
    elif echo "$newest_state" | grep -qE '([3-9][0-9]|[1-9][0-9]{2,}) minutes ago'; then
      is_old_enough=true
    fi

    [ "$is_old_enough" = "false" ] && continue

    retries=$(get_retry_count "$name")
    if [ "$retries" -ge "$MAX_RETRIES" ]; then
      continue
    fi

    log "HEALING: $name at $replicas (attempt $((retries + 1))/$MAX_RETRIES) — force-updating"
    if docker service update --detach --force "$name" 2>&1; then
      increment_retry "$name"
      log "HEALING: $name force-update sent"
    else
      log "HEALING: $name force-update FAILED"
    fi

  done

  sleep "$INTERVAL"
done
