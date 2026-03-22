#!/bin/sh
set -eu

###############################################################################
# ⚙️ CONFIG (env overrides)
###############################################################################
: "${RCLONE_FIX_ENABLED:=false}"
: "${RCLONE_FIX_INTERVAL:=60}"
: "${RCLONE_FIX_LOG_LEVEL:=INFO}"     # DEBUG | INFO | WARN | ERROR
: "${RCLONE_PLUGIN_NAME:=rclone}"
: "${RCLONE_STALE_REPAIR_ENABLED:=true}"
: "${RCLONE_STALE_PLUGIN_BASE:=/host-plugins}"

# You are mounting /var/lib/docker-plugins/rclone/cache/ to /state/
# Plugin typically stores docker-plugin.state in that cache dir.
: "${STATE_FILE:=/state/docker-plugin.state}"

# Probe settings (IMPORTANT: this is interpreted on the HOST by the plugin)
: "${RCLONE_PROBE_TYPE:=local}"       # rclone plugin option
: "${RCLONE_PROBE_PATH:=/tmp}"        # exists on virtually all Linux hosts

###############################################################################
# 🧰 LOGGING
###############################################################################
ts() { date '+%Y-%m-%d %H:%M:%S'; }

lvl_num() {
  case "$1" in
    DEBUG) echo 0 ;;
    INFO)  echo 1 ;;
    WARN)  echo 2 ;;
    ERROR) echo 3 ;;
    *)     echo 1 ;;
  esac
}

LOG_MIN="$(lvl_num "$RCLONE_FIX_LOG_LEVEL")"

log() {
  L="$1"; shift
  N="$(lvl_num "$L")"
  [ "$N" -lt "$LOG_MIN" ] && return 0

  case "$L" in
    DEBUG) EMO="🪵" ;;
    INFO)  EMO="ℹ️" ;;
    WARN)  EMO="⚠️" ;;
    ERROR) EMO="❌" ;;
    *)     EMO="🔹" ;;
  esac

  echo "$(ts) $EMO [$L] $*"
}

###############################################################################
# ✅ DEPENDENCIES (jq)
###############################################################################
if ! command -v jq >/dev/null 2>&1; then
  log WARN "jq not found. Installing… 🧩"
  if command -v apk >/dev/null 2>&1; then
    apk add --no-cache jq >/dev/null 2>&1 || { log ERROR "Failed to install jq 😵"; exit 1; }
    log INFO "jq installed ✅"
  else
    log ERROR "No supported package manager found to install jq. Exiting 🚪"
    exit 1
  fi
fi

###############################################################################
# 🛑 EARLY EXIT
###############################################################################
if [ "$RCLONE_FIX_ENABLED" != "true" ]; then
  log INFO "Fixer disabled (RCLONE_FIX_ENABLED=$RCLONE_FIX_ENABLED). Exiting 🛑"
  exit 0
fi

log INFO "Rclone fixer enabled ✅"
log INFO "Interval: ${RCLONE_FIX_INTERVAL}s ⏱️"
log INFO "Log level: ${RCLONE_FIX_LOG_LEVEL} 🗣️"
log INFO "Plugin: ${RCLONE_PLUGIN_NAME} 🔌"
log INFO "State file: ${STATE_FILE} 📄"
log INFO "Probe: type=${RCLONE_PROBE_TYPE} path=${RCLONE_PROBE_PATH} 🧪 (HOST path)"
log INFO "Stale repair: ${RCLONE_STALE_REPAIR_ENABLED} (base=${RCLONE_STALE_PLUGIN_BASE}) 🧹"

###############################################################################
# 🔎 BASIC CHECKS
###############################################################################
plugin_exists() {
  docker plugin inspect "$RCLONE_PLUGIN_NAME" >/dev/null 2>&1
}

plugin_enabled() {
  docker plugin inspect "$RCLONE_PLUGIN_NAME" -f '{{.Enabled}}' 2>/dev/null | grep -q true
}

###############################################################################
# 🧪 AUTHORITATIVE HEALTH CHECK (sidecar-safe)
# This forces Docker to call the plugin driver via docker.sock.
###############################################################################
probe_driver() {
  # Remove stale probe directories before creating a new unique probe.
  # This keeps unique probe naming while preventing unbounded probe-dir growth.
  cleanup_probe_dirs

  # BusyBox-safe uniqueness: seconds + PID
  V="__rclone_probe__$(date +%s)_$$"

  log DEBUG "Probe: docker volume create $V -d $RCLONE_PLUGIN_NAME … 🔬"
  if docker volume create "$V" -d "$RCLONE_PLUGIN_NAME" \
      -o "type=${RCLONE_PROBE_TYPE}" \
      -o "path=${RCLONE_PROBE_PATH}" >/dev/null 2>&1; then
    log DEBUG "Probe create ✅; removing volume 🧹"
    docker volume rm "$V" >/dev/null 2>&1 || true
    return 0
  fi

  # Best-effort cleanup in case create partially succeeded
  docker volume rm "$V" >/dev/null 2>&1 || true
  return 1
}

cleanup_probe_dirs() {
  PID="$(docker plugin inspect "$RCLONE_PLUGIN_NAME" -f '{{.ID}}' 2>/dev/null || true)"
  if [ -z "$PID" ]; then
    log INFO "Probe cleanup removed 0 dir(s) (plugin ID unavailable) 🧹"
    return 0
  fi

  BASE="${RCLONE_STALE_PLUGIN_BASE}/${PID}/propagated-mount"
  if [ ! -d "$BASE" ]; then
    log INFO "Probe cleanup removed 0 dir(s) (path missing: $BASE) 🧹"
    return 0
  fi

  COUNT="$(find "$BASE" -mindepth 1 -maxdepth 1 -type d -name '__rclone_probe__*' 2>/dev/null | wc -l | tr -d ' ')"
  [ -n "$COUNT" ] || COUNT="0"

  # Remove all historical probe directories before each probe run.
  # This follows the operational model: unique probe names, no leftover probes.
  if find "$BASE" -mindepth 1 -maxdepth 1 -type d -name '__rclone_probe__*' -exec rm -rf {} + >/dev/null 2>&1; then
    log INFO "Probe cleanup removed ${COUNT} dir(s) 🧹"
    return 0
  fi

  log WARN "Failed to fully cleanup probe directories under $BASE; continuing"
  return 0
}

###############################################################################
# 🧼 STATE CLEANUP
###############################################################################
clean_state_file() {
  if [ ! -f "$STATE_FILE" ]; then
    log WARN "State file not found at $STATE_FILE; skipping cleanup 🪹"
    return 0
  fi

  TMP_FILE="$(mktemp /tmp/docker-plugin.state.XXXXXX)"
  log INFO "Cleaning mounts in state file 🧼 ($STATE_FILE)"

  if jq 'map(.mounts = [])' "$STATE_FILE" > "$TMP_FILE"; then
    # atomic replace beats cp for 'resource busy'
    if mv -f "$TMP_FILE" "$STATE_FILE"; then
      log INFO "State file updated atomically ✅"
      return 0
    fi
    log WARN "Could not replace state file (resource busy?). Will retry next loop 🔁"
    rm -f "$TMP_FILE" >/dev/null 2>&1 || true
    return 1
  fi

  log ERROR "jq failed to process state file 😵"
  rm -f "$TMP_FILE" >/dev/null 2>&1 || true
  return 1
}

###############################################################################
# 🧯 REPAIR ROUTINE (disable -f → cleanup → enable → probe)
###############################################################################
repair() {
  log WARN "Repair started 🧯 (disable -f → cleanup → enable → probe)"

  log INFO "Disabling plugin (force) 🔻: docker plugin disable -f $RCLONE_PLUGIN_NAME"
  docker plugin disable -f "$RCLONE_PLUGIN_NAME" >/dev/null 2>&1 || log WARN "Disable returned non-zero (continuing) 🫠"

  clean_state_file || log WARN "State cleanup not fully successful (continuing) 🧷"

  log INFO "Enabling plugin 🔺: docker plugin enable $RCLONE_PLUGIN_NAME"
  if ! docker plugin enable "$RCLONE_PLUGIN_NAME" >/dev/null 2>&1; then
    log ERROR "Failed to enable plugin 😭"
    return 1
  fi
  log INFO "Plugin enabled ✅"

  log INFO "Post-repair probe 🧪"
  if probe_driver; then
    log INFO "Repair successful 🎉 (driver reachable)"
    return 0
  fi

  log ERROR "Repair finished but driver still unreachable 💥"
  return 1
}

###############################################################################
# 🧩 STALE MOUNT RECONCILIATION (volume metadata missing, stale path exists)
###############################################################################
# Resolves driver + opts from local container inspect (works on swarm workers).
# Service inspect is manager-only; HostConfig.Mounts[].VolumeOptions matches
# what we previously parsed from service specs.
rclone_volume_spec_from_local_containers() {
  VOL="$1"
  CIDS="$(docker ps -aq --filter "volume=$VOL" 2>/dev/null || true)"
  [ -n "$CIDS" ] || return 1

  docker inspect $CIDS 2>/dev/null | jq -c --arg vol "$VOL" '
    [ .[]
      | .HostConfig.Mounts[]?
      | select(.Type == "volume" and .Source == $vol)
      | select((.VolumeOptions.DriverConfig.Name // "") | test("^rclone"))
      | {
          name: (.VolumeOptions.DriverConfig.Name // "rclone"),
          opts: (.VolumeOptions.DriverConfig.Options // {})
        }
    ][0] // empty
  '
}

create_volume_from_spec() {
  VOL="$1"
  DRIVER="$2"
  OPTS_JSON="$3"

  # Build argv list without eval to prevent shell-injection on option keys/values.
  # set -- inside a function only modifies the function's own positional parameters.
  set -- docker volume create "$VOL" -d "$DRIVER"
  while IFS= read -r KV; do
    [ -n "$KV" ] || continue
    set -- "$@" -o "$KV"
  done <<EOF
$(echo "$OPTS_JSON" | jq -r 'to_entries[]? | "\(.key)=\(.value|tostring)"')
EOF

  "$@" >/dev/null 2>&1
}

reconcile_stale_mounts() {
  [ "$RCLONE_STALE_REPAIR_ENABLED" = "true" ] || return 0

  PID="$(docker plugin inspect "$RCLONE_PLUGIN_NAME" -f '{{.ID}}' 2>/dev/null || true)"
  if [ -z "$PID" ]; then
    log WARN "Could not resolve plugin ID; skipping stale mount reconciliation"
    return 0
  fi

  BASE="${RCLONE_STALE_PLUGIN_BASE}/${PID}/propagated-mount"
  if [ ! -d "$BASE" ]; then
    log DEBUG "No propagated-mount dir at $BASE"
    return 0
  fi

  REPAIRED=0
  for D in "$BASE"/*; do
    [ -d "$D" ] || continue
    VOL="$(basename "$D")"

    if docker volume inspect "$VOL" >/dev/null 2>&1; then
      continue
    fi

    if [ -z "$(ls -A "$D" 2>/dev/null || true)" ]; then
      continue
    fi

    SPEC="$(rclone_volume_spec_from_local_containers "$VOL" || true)"
    if [ -z "$SPEC" ]; then
      log WARN "Stale dir for '$VOL' found, but no matching rclone mount spec from local containers. Skipping."
      continue
    fi

    DRIVER="$(echo "$SPEC" | jq -r '.name // empty')"
    OPTS="$(echo "$SPEC" | jq -c '.opts // {}')"
    if [ -z "$DRIVER" ]; then
      log WARN "Driver missing in spec for '$VOL'; skipping."
      continue
    fi

    log WARN "Stale mount mismatch detected for '$VOL' (missing volume + non-empty path). Recreating without backup."
    if ! rm -rf "$D" >/dev/null 2>&1; then
      log ERROR "Failed to remove stale dir for '$VOL': $D"
      continue
    fi

    if create_volume_from_spec "$VOL" "$DRIVER" "$OPTS"; then
      log INFO "Recreated rclone volume '$VOL' from local container mount spec ✅"
      REPAIRED=$((REPAIRED + 1))
    else
      log ERROR "Failed to recreate rclone volume '$VOL'"
    fi
  done

  if [ "$REPAIRED" -gt 0 ]; then
    log INFO "Stale mount reconciliation repaired ${REPAIRED} volume(s) 🎉"
  fi
}

###############################################################################
# 🔁 MAIN LOOP
###############################################################################
log INFO "Starting loop ♾️"

while true; do
  log INFO "Tick 🕰️ (next check in ${RCLONE_FIX_INTERVAL}s)"

  if ! plugin_exists; then
    log ERROR "Plugin '$RCLONE_PLUGIN_NAME' not found 🤷‍♂️"
    sleep "$RCLONE_FIX_INTERVAL"
    continue
  fi

  if ! plugin_enabled; then
    log WARN "Plugin is disabled 📴 — repairing… 🛠️"
    repair || log ERROR "Repair attempt failed; will retry next cycle 🔁"
    sleep "$RCLONE_FIX_INTERVAL"
    continue
  fi

  if probe_driver; then
    log INFO "🟢 rclone OK (driver reachable) 🙌"
    reconcile_stale_mounts
  else
    log WARN "🔴 rclone unhealthy (driver probe failed) 🧨 — repairing… 🛠️"
    repair || log ERROR "Repair attempt failed; will retry next cycle 🔁"
  fi

  sleep "$RCLONE_FIX_INTERVAL"
done
