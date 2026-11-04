#!/bin/sh
set -eu

###############################################################################
# ⚙️ CONFIG (env overrides)
###############################################################################
: "${RCLONE_FIXER_TEST_MODE:=0}"
: "${RCLONE_FIX_ENABLED:=false}"
: "${RCLONE_FIX_INTERVAL:=60}"
: "${RCLONE_FIX_LOG_LEVEL:=INFO}"     # DEBUG | INFO | WARN | ERROR
: "${RCLONE_PLUGIN_NAME:=rclone}"
: "${RCLONE_STALE_REPAIR_ENABLED:=true}"  # legacy alias; controls reconcile_volumes
: "${RCLONE_STALE_PLUGIN_BASE:=/host-plugins}"

# You are mounting /var/lib/docker-plugins/rclone/cache/ to /state/
# Plugin typically stores docker-plugin.state in that cache dir.
: "${STATE_FILE:=/state/docker-plugin.state}"

# Probe settings (IMPORTANT: this is interpreted on the HOST by the plugin)
: "${RCLONE_PROBE_TYPE:=local}"       # rclone plugin option
: "${RCLONE_PROBE_PATH:=/tmp}"        # exists on virtually all Linux hosts
: "${RCLONE_PROBE_TIMEOUT_SECONDS:=15}"
: "${RCLONE_ENABLE_TIMEOUT_SECONDS:=300}"

# Volume reconciliation controller (replaces standalone reconcile_stale_mounts).
# Every tick, derives desired rclone-volume state from local container specs
# and converges actual state toward it. Handles missing volumes, wrong driver,
# and missing/wrong labels uniformly via destroy → recreate.
#
# No backup/restore: rclone volumes are GCS-backed; the local mount is just
# VFS cache that the plugin will rebuild on next mount. Destroying the local
# volume is a cache-invalidate operation, not data loss.

# Per-volume cooldown after a failed rclone-driver recreate (which falls back
# to local). Prevents thrashing the same volume's destroy/recreate cycle every
# tick when the plugin is degraded but not unhealthy enough to fail the probe.
# Cleared on successful rclone-driver create.
: "${RCLONE_RECONCILE_COOLDOWN_SECONDS:=300}"

# Where per-volume cooldown markers live. /tmp inside the container is fine —
# stale marker after a fixer restart at worst causes one extra reconcile attempt.
: "${RCLONE_RECONCILE_STATE_DIR:=/tmp}"
: "${RCLONE_REPAIR_COOLDOWN_SECONDS:=300}"
: "${RCLONE_REPAIR_LOCK_DIR:=${RCLONE_RECONCILE_STATE_DIR}/.rclone-repair.lock}"
: "${RCLONE_REPAIR_COOLDOWN_FILE:=${RCLONE_RECONCILE_STATE_DIR}/.rclone-repair-cooldown}"

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
# ✅ DEPENDENCIES (jq only — backup/restore tools no longer needed)
###############################################################################
if [ "$RCLONE_FIXER_TEST_MODE" != "1" ]; then
for DEP in jq; do
  if ! command -v "$DEP" >/dev/null 2>&1; then
    log WARN "$DEP not found. Installing… 🧩"
    if command -v apk >/dev/null 2>&1; then
      apk add --no-cache "$DEP" >/dev/null 2>&1 || { log ERROR "Failed to install $DEP 😵"; exit 1; }
      log INFO "$DEP installed ✅"
    else
      log ERROR "No supported package manager found to install $DEP. Exiting 🚪"
      exit 1
    fi
  fi
done

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
log INFO "Reconcile: ${RCLONE_STALE_REPAIR_ENABLED} (cooldown=${RCLONE_RECONCILE_COOLDOWN_SECONDS}s) 🔁"

mkdir -p "$RCLONE_RECONCILE_STATE_DIR" 2>/dev/null || true
fi

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
  cleanup_probe_dirs

  case "$RCLONE_PROBE_TIMEOUT_SECONDS" in
    ''|0|*[!0-9]*)
      log ERROR "Invalid probe timeout: $RCLONE_PROBE_TIMEOUT_SECONDS"
      return 1
      ;;
  esac

  # BusyBox-safe uniqueness: seconds + PID
  V="__rclone_probe__$(date +%s)_$$"

  log DEBUG "Probe: bounded docker volume create $V -d $RCLONE_PLUGIN_NAME"
  if timeout "$RCLONE_PROBE_TIMEOUT_SECONDS" docker volume create "$V" -d "$RCLONE_PLUGIN_NAME" \
      -o "type=${RCLONE_PROBE_TYPE}" \
      -o "path=${RCLONE_PROBE_PATH}" >/dev/null 2>&1; then
    log DEBUG "Probe create succeeded; removing volume"
    timeout "$RCLONE_PROBE_TIMEOUT_SECONDS" docker volume rm "$V" >/dev/null 2>&1 || true
    return 0
  fi

  # Best-effort bounded cleanup in case create partially succeeded.
  timeout "$RCLONE_PROBE_TIMEOUT_SECONDS" docker volume rm "$V" >/dev/null 2>&1 || true
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
    log WARN "State file not found at $STATE_FILE; skipping cleanup"
    return 0
  fi

  TMP_FILE="$(mktemp "${STATE_FILE}.tmp.XXXXXX")"
  DESIRED_FILE="$(mktemp "${STATE_FILE}.desired.XXXXXX")"
  derive_desired_volumes | cut -f1 > "$DESIRED_FILE" 2>/dev/null || true

  if ! jq --rawfile desired "$DESIRED_FILE" '
      ($desired | split("\n") | map(select(length > 0))) as $desired_names
      | map(if (.name as $name | $desired_names | index($name)) then . else .mounts = [] end)
    ' "$STATE_FILE" > "$TMP_FILE"; then
    log ERROR "jq failed to process state file"
    rm -f "$TMP_FILE" "$DESIRED_FILE" >/dev/null 2>&1 || true
    return 1
  fi
  rm -f "$DESIRED_FILE"

  MODE="$(stat -c %a "$STATE_FILE")"
  BACKUP_FILE="${STATE_FILE}.bak.$(date +%s).$$"
  if ! cp -p "$STATE_FILE" "$BACKUP_FILE"; then
    log ERROR "Could not create full state backup; original left unchanged"
    rm -f "$TMP_FILE" >/dev/null 2>&1 || true
    return 1
  fi
  if ! chmod "$MODE" "$TMP_FILE"; then
    log ERROR "Could not preserve state file mode; original left unchanged"
    rm -f "$TMP_FILE" >/dev/null 2>&1 || true
    return 1
  fi

  log INFO "Cleaning stale mounts in state file ($STATE_FILE)"
  if mv -f "$TMP_FILE" "$STATE_FILE"; then
    log INFO "State file updated atomically"
    return 0
  fi

  log WARN "Could not replace state file (resource busy?). Will retry next loop"
  rm -f "$TMP_FILE" >/dev/null 2>&1 || true
  return 1
}

stale_state_exists() {
  [ -f "$STATE_FILE" ] || return 1
  DESIRED_FILE="$(mktemp "${STATE_FILE}.desired.XXXXXX")"
  derive_desired_volumes | cut -f1 > "$DESIRED_FILE" 2>/dev/null || true
  if jq -e --rawfile desired "$DESIRED_FILE" '
      ($desired | split("\n") | map(select(length > 0))) as $desired_names
      | any(.[]; ((.mounts // []) | length) > 0 and (.name as $name | $desired_names | index($name) | not))
    ' "$STATE_FILE" >/dev/null 2>&1; then
    rm -f "$DESIRED_FILE"
    return 0
  fi
  rm -f "$DESIRED_FILE"
  return 1
}


bounded_volume_get() {
  VOLUME_NAME="$1"
  case "$RCLONE_PROBE_TIMEOUT_SECONDS" in
    ''|0|*[!0-9]*)
      log ERROR "Invalid probe timeout: $RCLONE_PROBE_TIMEOUT_SECONDS"
      return 1
      ;;
  esac
  timeout "$RCLONE_PROBE_TIMEOUT_SECONDS" docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1
}

state_volume_has_mounts() {
  VOLUME_NAME="$1"
  [ -f "$STATE_FILE" ] || return 1
  jq -e --arg name "$VOLUME_NAME" '
    any(.[]; .name == $name and ((.mounts // []) | length) > 0)
  ' "$STATE_FILE" >/dev/null 2>&1
}

local_container_refs_volume() {
  VOLUME_NAME="$1"
  REFS="$(docker ps -aq --filter "volume=${VOLUME_NAME}" 2>/dev/null || true)"
  [ -n "$REFS" ]
}

clear_state_mounts_for_volume() {
  VOLUME_NAME="$1"
  if [ ! -f "$STATE_FILE" ]; then
    log ERROR "State file not found at $STATE_FILE; refusing targeted cleanup for $VOLUME_NAME"
    return 1
  fi
  if ! state_volume_has_mounts "$VOLUME_NAME"; then
    log ERROR "No mounted state entry found for $VOLUME_NAME; refusing targeted cleanup"
    return 1
  fi

  TMP_FILE="$(mktemp "${STATE_FILE}.tmp.XXXXXX")"
  if ! jq --arg name "$VOLUME_NAME" '
      map(if .name == $name then .mounts = [] else . end)
    ' "$STATE_FILE" > "$TMP_FILE"; then
    log ERROR "jq failed to process state file for $VOLUME_NAME"
    rm -f "$TMP_FILE" >/dev/null 2>&1 || true
    return 1
  fi

  MODE="$(stat -c %a "$STATE_FILE")"
  BACKUP_FILE="${STATE_FILE}.bak.$(date +%s).$$"
  if ! cp -p "$STATE_FILE" "$BACKUP_FILE"; then
    log ERROR "Could not create full state backup for $VOLUME_NAME; original left unchanged"
    rm -f "$TMP_FILE" >/dev/null 2>&1 || true
    return 1
  fi
  if ! chmod "$MODE" "$TMP_FILE"; then
    log ERROR "Could not preserve state file mode for $VOLUME_NAME; original left unchanged"
    rm -f "$TMP_FILE" >/dev/null 2>&1 || true
    return 1
  fi

  log WARN "Clearing stale persisted mount state for $VOLUME_NAME"
  if mv -f "$TMP_FILE" "$STATE_FILE"; then
    log INFO "State file updated atomically for $VOLUME_NAME"
    return 0
  fi

  log WARN "Could not replace state file for $VOLUME_NAME (resource busy?). Will retry next loop"
  rm -f "$TMP_FILE" >/dev/null 2>&1 || true
  return 1
}

recover_stale_mounted_volume() {
  VOLUME_NAME="$1"
  if local_container_refs_volume "$VOLUME_NAME"; then
    log ERROR "Volume $VOLUME_NAME still has local container references; refusing targeted state cleanup"
    return 1
  fi
  if ! clear_state_mounts_for_volume "$VOLUME_NAME"; then
    return 1
  fi

  log WARN "Reloading $RCLONE_PLUGIN_NAME after targeted state cleanup for $VOLUME_NAME"
  if ! docker plugin disable "$RCLONE_PLUGIN_NAME" >/dev/null 2>&1; then
    log ERROR "Could not disable $RCLONE_PLUGIN_NAME for targeted recovery of $VOLUME_NAME"
    return 1
  fi
  if ! enable_plugin_bounded; then
    log ERROR "Could not re-enable $RCLONE_PLUGIN_NAME for targeted recovery of $VOLUME_NAME"
    return 1
  fi
  if bounded_volume_get "$VOLUME_NAME"; then
    log INFO "Targeted recovery successful for $VOLUME_NAME (VolumeDriver.Get reachable)"
    return 0
  fi

  log ERROR "Targeted recovery finished but VolumeDriver.Get still failed for $VOLUME_NAME"
  return 1
}

recover_timed_out_mounted_volumes() {
  [ -f "$STATE_FILE" ] || return 0
  VOLUME_NAMES="$(jq -r '.[] | select(((.mounts // []) | length) > 0) | .name' "$STATE_FILE" 2>/dev/null || true)"
  [ -n "$VOLUME_NAMES" ] || return 0

  for VOLUME_NAME in $VOLUME_NAMES; do
    if bounded_volume_get "$VOLUME_NAME"; then
      log DEBUG "VolumeDriver.Get reachable for mounted state volume $VOLUME_NAME"
      continue
    fi
    log WARN "VolumeDriver.Get timed out or failed for mounted state volume $VOLUME_NAME"
    recover_stale_mounted_volume "$VOLUME_NAME" || return 1
  done
  return 0
}

repair_cooldown_active() {
  [ -f "$RCLONE_REPAIR_COOLDOWN_FILE" ] || return 1
  LAST="$(cat "$RCLONE_REPAIR_COOLDOWN_FILE" 2>/dev/null || echo 0)"
  case "$LAST" in
    ''|*[!0-9]*) LAST=0 ;;
  esac
  AGE=$(( $(date +%s) - LAST ))
  [ "$AGE" -lt "$RCLONE_REPAIR_COOLDOWN_SECONDS" ]
}

set_repair_cooldown() {
  date +%s > "$RCLONE_REPAIR_COOLDOWN_FILE"
}

###############################################################################
# REPAIR ROUTINE (non-destructive restart/probe, then guarded stale cleanup)
###############################################################################
enable_plugin_bounded() {
  case "$RCLONE_ENABLE_TIMEOUT_SECONDS" in
    ''|0|*[!0-9]*)
      log ERROR "Invalid plugin enable timeout: $RCLONE_ENABLE_TIMEOUT_SECONDS"
      return 1
      ;;
  esac
  timeout "$((RCLONE_ENABLE_TIMEOUT_SECONDS + 30))" \
    docker plugin enable --timeout "$RCLONE_ENABLE_TIMEOUT_SECONDS" "$RCLONE_PLUGIN_NAME" >/dev/null 2>&1
}

recover_disabled_plugin() {
  log WARN "Disabled plugin recovery: cleaning state file before bounded enable"
  if ! clean_state_file; then
    log ERROR "State cleanup failed before disabled-plugin enable; refusing to continue"
    return 1
  fi

  if ! enable_plugin_bounded; then
    log ERROR "Failed to enable disabled plugin within ${RCLONE_ENABLE_TIMEOUT_SECONDS}s"
    return 1
  fi

  if probe_driver; then
    log INFO "Disabled plugin recovery successful (driver reachable after enable)"
    return 0
  fi

  log ERROR "Plugin enabled but driver still unreachable after disabled-plugin recovery"
  return 1
}

repair() {
  log WARN "Repair started (non-destructive restart then probe)"

  if docker plugin disable "$RCLONE_PLUGIN_NAME" >/dev/null 2>&1; then
    if ! enable_plugin_bounded; then
      log ERROR "Failed to enable plugin after non-destructive restart"
      return 1
    fi
  else
    log WARN "Non-force disable returned non-zero; probing current plugin state"
  fi
  if probe_driver; then
    log INFO "Repair successful (non-destructive restart recovered driver)"
    return 0
  fi

  if ! stale_state_exists; then
    log ERROR "Driver unreachable but no proven stale mounts; refusing destructive repair"
    return 1
  fi

  mkdir -p "$RCLONE_RECONCILE_STATE_DIR" 2>/dev/null || return 1
  if repair_cooldown_active; then
    log WARN "Destructive repair cooldown active; refusing repeated cleanup"
    return 1
  fi
  if ! mkdir "$RCLONE_REPAIR_LOCK_DIR" 2>/dev/null; then
    log WARN "Another destructive repair holds the exclusive lock"
    return 1
  fi

  if repair_cooldown_active || ! stale_state_exists; then
    rmdir "$RCLONE_REPAIR_LOCK_DIR" 2>/dev/null || true
    return 1
  fi
  set_repair_cooldown

  log WARN "Proven stale mounts remain; entering guarded destructive repair"
  docker plugin disable -f "$RCLONE_PLUGIN_NAME" >/dev/null 2>&1 || \
    log WARN "Force disable returned non-zero (continuing)"
  clean_state_file || log WARN "State cleanup not fully successful (continuing)"

  if ! enable_plugin_bounded; then
    log ERROR "Failed to enable plugin after stale cleanup"
    rmdir "$RCLONE_REPAIR_LOCK_DIR" 2>/dev/null || true
    return 1
  fi
  if probe_driver; then
    log INFO "Repair successful (driver reachable after stale cleanup)"
    rmdir "$RCLONE_REPAIR_LOCK_DIR" 2>/dev/null || true
    return 0
  fi

  log ERROR "Repair finished but driver still unreachable"
  rmdir "$RCLONE_REPAIR_LOCK_DIR" 2>/dev/null || true
  return 1
}

###############################################################################
# 🔁 VOLUME CONTROLLER
#
# Single reconciliation pass per tick. Walks local running/created containers
# to derive the desired rclone-volume state, compares against the actual local
# Docker volume state, and applies the smallest reconciling action per volume.
#
# Failure modes handled uniformly:
#   - Missing volume:    create with desired driver/options/labels.
#   - Wrong driver:      destroy + recreate.
#   - Missing/wrong labels: destroy + recreate.
#   - Stale propagated-mount dir without container reference: ignored (volume
#     was abandoned upstream; recreating it without a consumer would be wrong).
#
# No backup/restore: rclone volumes are GCS-backed; the local mount is just
# VFS cache that the plugin rebuilds from the remote on next mount. Destroying
# the local volume is a cache-invalidate, not data loss.
#
# Safety rails:
#   - destroy_volume_safely stops local containers using the volume so docker
#     volume rm can succeed; Swarm reschedules them onto the recreated volume.
#   - If recreate with rclone driver fails → fall back to a local-driver
#     placeholder WITH the desired stack labels, set per-volume cooldown, and
#     retry rclone after RCLONE_RECONCILE_COOLDOWN_SECONDS. Labels on the
#     fallback prevent immediate re-detection of label drift, which would
#     otherwise be an infinite loop.
#   - Volumes not in the desired set are never touched.
#   - Reconciliation only runs when the plugin probe passes, to avoid
#     amplifying distress.
###############################################################################

# Emit one TSV record per desired rclone volume from local container specs.
# Format: <name>\t<driver>\t<opts_json>\t<labels_json>
#
# Labels come from .VolumeOptions.Labels on the mount spec — that's where
# Swarm injects the stack-ownership labels (com.docker.stack.namespace etc.)
# it expects the volume to carry. Container-level Config.Labels are about the
# image/service identity, not the volume, and using them was wrong.
#
# Container filter: only running + created. Skipping dead/exited containers
# avoids inspecting hundreds of stale entries every 60s — those don't reflect
# current desired state anyway.
derive_desired_volumes() {
  CIDS="$(docker ps -q --filter status=running --filter status=created 2>/dev/null || true)"
  [ -n "$CIDS" ] || return 0

  # Pipe CIDS through xargs instead of bare shell expansion. With many
  # containers, `docker inspect $CIDS` silently fails (ARG_MAX overflow or
  # internal Docker buffering) and returns empty — which makes the controller
  # think there are zero desired rclone volumes and never reconcile.
  # xargs handles the chunking transparently.
  echo "$CIDS" | xargs docker inspect 2>/dev/null | jq -r '
    [ .[]
      | .HostConfig.Mounts[]?
      | select(.Type == "volume")
      | select((.VolumeOptions.DriverConfig.Name // "") | test("^rclone"))
      | {
          name: .Source,
          driver: (.VolumeOptions.DriverConfig.Name // "rclone"),
          opts: (.VolumeOptions.DriverConfig.Options // {}),
          labels: (.VolumeOptions.Labels // {})
        }
    ]
    | group_by(.name) | map(.[0])
    | .[]
    | [.name, .driver, (.opts | @json), (.labels | @json)] | @tsv
  '
}

# Fetch the actual driver / labels / options / mountpoint for a single volume.
# Returns empty (rc 1) if the volume does not exist locally.
# Format on success: <driver>\t<labels_json>\t<options_json>\t<mountpoint>
get_actual_volume() {
  VOL="$1"
  docker volume inspect "$VOL" 2>/dev/null | jq -r '
    .[0]
    | [
        (.Driver // ""),
        ((.Labels // {}) | @json),
        ((.Options // {}) | @json),
        (.Mountpoint // "")
      ]
    | @tsv
  ' 2>/dev/null
}

# Stop local containers using the volume and remove the local volume entry.
# Containers are stopped via `docker stop` (graceful, 30s timeout) — Swarm
# observes the task die and reschedules with the recreated volume.
# Returns 0 on success, 1 if the volume can't be removed (still in use).
destroy_volume_safely() {
  VOL="$1"

  USING="$(docker ps -q --filter "volume=$VOL" 2>/dev/null || true)"

  if [ -n "$USING" ]; then
    log WARN "destroy_volume_safely: stopping local containers holding '$VOL': $USING"
    for C in $USING; do
      docker stop -t 30 "$C" >/dev/null 2>&1 || \
        log WARN "destroy_volume_safely: failed to stop $C, continuing"
    done
    sleep 2
  fi

  if ! docker volume rm "$VOL" >/dev/null 2>&1; then
    log ERROR "destroy_volume_safely: docker volume rm failed for '$VOL' (still in use?)"
    return 1
  fi

  return 0
}

# Build a `docker volume create` invocation from name + driver + opts (JSON
# object) + labels (JSON object). Avoids eval — uses set-- positional args.
create_volume_from_spec() {
  VOL="$1"
  DRIVER="$2"
  OPTS_JSON="${3:-{}}"
  LABELS_JSON="${4:-{}}"

  set -- docker volume create "$VOL" -d "$DRIVER"

  while IFS= read -r KV; do
    [ -n "$KV" ] || continue
    set -- "$@" -o "$KV"
  done <<EOF
$(echo "$OPTS_JSON" | jq -r 'to_entries[]? | "\(.key)=\(.value|tostring)"')
EOF

  while IFS= read -r KV; do
    [ -n "$KV" ] || continue
    set -- "$@" -l "$KV"
  done <<EOF
$(echo "$LABELS_JSON" | jq -r 'to_entries[]? | "\(.key)=\(.value|tostring)"')
EOF

  "$@" >/dev/null 2>&1
}

# Per-volume cooldown markers — track when we last fell back to a local-driver
# placeholder for a given volume, so we don't re-attempt destroy+recreate every
# tick against a still-degraded plugin. Markers live in the same dir as backups
# (default /tmp inside the container — ephemeral, which is fine: a stale marker
# at worst causes one extra reconcile attempt after a fixer restart).
cooldown_marker_path() {
  echo "${RCLONE_RECONCILE_STATE_DIR}/.reconcile-cooldown-$1"
}

cooldown_active() {
  VOL="$1"
  MARKER="$(cooldown_marker_path "$VOL")"
  [ -f "$MARKER" ] || return 1
  LAST="$(cat "$MARKER" 2>/dev/null || echo 0)"
  case "$LAST" in
    ''|*[!0-9]*) LAST=0 ;;
  esac
  NOW="$(date +%s)"
  AGE=$((NOW - LAST))
  [ "$AGE" -lt "$RCLONE_RECONCILE_COOLDOWN_SECONDS" ]
}

set_cooldown() {
  VOL="$1"
  date +%s > "$(cooldown_marker_path "$VOL")" 2>/dev/null || true
}

clear_cooldown() {
  VOL="$1"
  rm -f "$(cooldown_marker_path "$VOL")" 2>/dev/null || true
}

# Decide if actual labels satisfy desired labels.
# Returns 0 if every desired key is present in actual with the same value.
# Returns 1 if any drift detected.
labels_match() {
  DESIRED_JSON="$1"
  ACTUAL_JSON="${2:-{}}"
  [ -z "$ACTUAL_JSON" ] || [ "$ACTUAL_JSON" = "null" ] && ACTUAL_JSON="{}"

  DRIFT="$(echo "$DESIRED_JSON" | jq -c --argjson actual "$ACTUAL_JSON" '
    to_entries
    | map(select(($actual[.key] // null) != .value))
    | length > 0
  ' 2>/dev/null)"

  [ "$DRIFT" = "false" ]
}

# Reconciliation pass: drive actual rclone-volume state on this node toward
# what local container specs describe.
reconcile_volumes() {
  [ "$RCLONE_STALE_REPAIR_ENABLED" = "true" ] || return 0

  DESIRED_FILE="$(mktemp /tmp/rclone-fixer-desired.XXXXXX)"
  derive_desired_volumes > "$DESIRED_FILE" 2>/dev/null || true

  if [ ! -s "$DESIRED_FILE" ]; then
    log DEBUG "reconcile_volumes: no rclone volumes desired on this node"
    rm -f "$DESIRED_FILE"
    return 0
  fi

  RECONCILED=0
  FAILED=0
  SKIPPED=0

  TAB="$(printf '\t')"
  while IFS="$TAB" read -r NAME DRIVER OPTS LABELS; do
    [ -n "$NAME" ] || continue
    [ -n "$DRIVER" ] || { log WARN "reconcile_volumes: skipping '$NAME' (no driver in spec)"; SKIPPED=$((SKIPPED + 1)); continue; }

    log DEBUG "reconcile_volumes: examining '$NAME' (desired driver=$DRIVER)"

    ACTUAL="$(get_actual_volume "$NAME" || true)"

    # ----- Branch A: volume missing → create -----
    if [ -z "$ACTUAL" ]; then
      if cooldown_active "$NAME"; then
        log INFO "reconcile_volumes: '$NAME' missing but cooldown active (recent fallback) — skipping create attempt"
        SKIPPED=$((SKIPPED + 1))
        continue
      fi
      log INFO "reconcile_volumes: '$NAME' missing → creating with driver=$DRIVER"
      if create_volume_from_spec "$NAME" "$DRIVER" "$OPTS" "$LABELS"; then
        log INFO "reconcile_volumes: '$NAME' created ✅"
        clear_cooldown "$NAME"
        RECONCILED=$((RECONCILED + 1))
      else
        log ERROR "reconcile_volumes: create failed for '$NAME' (plugin may not be ready) — setting cooldown"
        set_cooldown "$NAME"
        FAILED=$((FAILED + 1))
      fi
      continue
    fi

    # Parse actual fields
    ACTUAL_DRIVER="$(echo "$ACTUAL" | cut -f1)"
    ACTUAL_LABELS="$(echo "$ACTUAL" | cut -f2)"

    # ----- Compute drift -----
    DRIVER_DRIFT=false
    case "$ACTUAL_DRIVER" in
      rclone*) ;;  # any rclone[:tag] is acceptable
      *) DRIVER_DRIFT=true ;;
    esac

    LABEL_DRIFT=false
    if ! labels_match "$LABELS" "$ACTUAL_LABELS"; then
      LABEL_DRIFT=true
    fi

    if [ "$DRIVER_DRIFT" = "false" ] && [ "$LABEL_DRIFT" = "false" ]; then
      log DEBUG "reconcile_volumes: '$NAME' OK (driver=$ACTUAL_DRIVER, labels match)"
      continue
    fi
    if [ "$DRIVER_DRIFT" = "false" ]; then
      log WARN "reconcile_volumes: '$NAME' label-only drift ignored for healthy rclone volume"
      continue
    fi

    # ----- Branch B: drift → destroy + recreate -----
    # No backup/restore: rclone volumes are GCS-backed; the local mount is just
    # VFS cache that the plugin rebuilds on next mount. Destroying the local
    # volume invalidates the cache; recreate triggers a fresh rclone mount
    # which re-syncs from the remote.
    if cooldown_active "$NAME"; then
      log INFO "reconcile_volumes: '$NAME' drift detected but cooldown active (recent fallback) — skipping reconcile"
      SKIPPED=$((SKIPPED + 1))
      continue
    fi

    log WARN "reconcile_volumes: '$NAME' DRIFT (driver_drift=$DRIVER_DRIFT label_drift=$LABEL_DRIFT) → reconciling"

    # Audit log: capture size + file count of what's about to be destroyed.
    # Only works when the volume is rclone-driven (propagated-mount path
    # exists) — for driver-drift cases where the actual driver is local, the
    # local mountpoint is under /var/lib/docker/volumes/ which the fixer
    # doesn't have bind access to. In that case we log "size=unknown" so the
    # operator knows the audit was attempted but had nothing to report.
    PID="$(docker plugin inspect "$RCLONE_PLUGIN_NAME" -f '{{.ID}}' 2>/dev/null || true)"
    PROP_PATH="${RCLONE_STALE_PLUGIN_BASE}/${PID}/propagated-mount/${NAME}"
    if [ -n "$PID" ] && [ -d "$PROP_PATH" ]; then
      VOL_SIZE="$(du -sh "$PROP_PATH" 2>/dev/null | cut -f1)"
      VOL_FILES="$(find "$PROP_PATH" -type f 2>/dev/null | wc -l | tr -d ' ')"
      log WARN "reconcile_volumes: destroying '$NAME' (size=${VOL_SIZE:-?} files=${VOL_FILES:-?}) — local cache invalidated; rclone will re-sync from remote on next mount"
    else
      log WARN "reconcile_volumes: destroying '$NAME' (size=unknown — propagated-mount not accessible; likely a wrong-driver volume) — local-only writes during the wrong-driver window will be lost"
    fi

    if ! destroy_volume_safely "$NAME"; then
      log ERROR "reconcile_volumes: destroy failed for '$NAME' — setting cooldown to avoid retry storm (Swarm may have re-mounted between stop and rm)"
      set_cooldown "$NAME"
      FAILED=$((FAILED + 1))
      continue
    fi

    # Try recreate with desired (rclone) driver first.
    if create_volume_from_spec "$NAME" "$DRIVER" "$OPTS" "$LABELS"; then
      clear_cooldown "$NAME"
      log INFO "reconcile_volumes: '$NAME' reconciled ✅ (rclone will re-sync from remote on next mount)"
      RECONCILED=$((RECONCILED + 1))
      continue
    fi

    # Recreate with rclone driver failed (e.g. plugin race, hostpath issue).
    # Fall back to a local-driver placeholder WITH the desired labels so
    # dependent services aren't permanently broken. Set per-volume cooldown
    # to avoid thrashing destroy/recreate every tick — rclone driver will be
    # retried after RCLONE_RECONCILE_COOLDOWN_SECONDS.
    #
    # Labels on the fallback are critical: without them, the very next pass
    # would detect label drift and trigger another destroy/recreate cycle,
    # producing the infinite-loop the cooldown is meant to break.
    log WARN "reconcile_volumes: rclone-driver recreate failed for '$NAME' — falling back to local driver placeholder; cooldown ${RCLONE_RECONCILE_COOLDOWN_SECONDS}s before retry"
    if create_volume_from_spec "$NAME" local "{}" "$LABELS"; then
      set_cooldown "$NAME"
      log WARN "reconcile_volumes: '$NAME' on fallback local driver with stack labels; will retry rclone after cooldown"
      RECONCILED=$((RECONCILED + 1))
    else
      log ERROR "reconcile_volumes: even local-driver fallback failed for '$NAME'"
      set_cooldown "$NAME"
      FAILED=$((FAILED + 1))
    fi
  done < "$DESIRED_FILE"

  rm -f "$DESIRED_FILE"

  if [ "$RECONCILED" -gt 0 ] || [ "$FAILED" -gt 0 ] || [ "$SKIPPED" -gt 0 ]; then
    log INFO "reconcile_volumes: pass complete (reconciled=$RECONCILED failed=$FAILED skipped=$SKIPPED)"
  fi
}


###############################################################################
# 📊 VFS CACHE METRICS (textfile collector for node_exporter)
###############################################################################
: "${METRICS_DIR:=/metrics}"
: "${METRICS_ENABLED:=true}"
RCLONE_LAST_PROBE_OK=1

collect_metrics() {
  [ "$METRICS_ENABLED" = "true" ] || return 0
  [ -d "$METRICS_DIR" ] || { log DEBUG "Metrics dir $METRICS_DIR not found; skipping"; return 0; }

  PROM_FILE="$METRICS_DIR/rclone_vfs_cache.prom"
  TMP_PROM="$(mktemp "$METRICS_DIR/.rclone_vfs_cache.prom.XXXXXX" 2>/dev/null)" || return 0

  {
    echo "# HELP rclone_vfs_cache_bytes Total VFS cache size in bytes"
    echo "# TYPE rclone_vfs_cache_bytes gauge"
    echo "# HELP rclone_vfs_cache_meta_bytes Total VFS metadata size in bytes"
    echo "# TYPE rclone_vfs_cache_meta_bytes gauge"
    echo "# HELP rclone_vfs_cache_remote_bytes Per-remote VFS cache size in bytes"
    echo "# TYPE rclone_vfs_cache_remote_bytes gauge"
    echo "# HELP rclone_vfs_volumes_total Total number of rclone volumes"
    echo "# TYPE rclone_vfs_volumes_total gauge"
    echo "# HELP rclone_vfs_volumes_active Number of actively mounted volumes"
    echo "# TYPE rclone_vfs_volumes_active gauge"
    echo "# HELP rclone_vfs_cache_available_bytes Available disk space on cache partition"
    echo "# TYPE rclone_vfs_cache_available_bytes gauge"
    echo "# HELP rclone_vfs_plugin_healthy Whether the rclone plugin is responding (1=yes, 0=no)"
    echo "# TYPE rclone_vfs_plugin_healthy gauge"

    # Total VFS cache size
    if [ -d "/state/vfs" ]; then
      VFS_BYTES="$(du -sb /state/vfs 2>/dev/null | awk '{print $1}')"
      echo "rclone_vfs_cache_bytes ${VFS_BYTES:-0}"
    else
      echo "rclone_vfs_cache_bytes 0"
    fi

    # VFS metadata size
    if [ -d "/state/vfsMeta" ]; then
      META_BYTES="$(du -sb /state/vfsMeta 2>/dev/null | awk '{print $1}')"
      echo "rclone_vfs_cache_meta_bytes ${META_BYTES:-0}"
    else
      echo "rclone_vfs_cache_meta_bytes 0"
    fi

    # Per-remote cache sizes
    if [ -d "/state/vfs" ]; then
      for REMOTE_DIR in /state/vfs/*/; do
        [ -d "$REMOTE_DIR" ] || continue
        REMOTE_NAME="$(basename "$REMOTE_DIR")"
        REMOTE_BYTES="$(du -sb "$REMOTE_DIR" 2>/dev/null | awk '{print $1}')"
        echo "rclone_vfs_cache_remote_bytes{remote=\"${REMOTE_NAME}\"} ${REMOTE_BYTES:-0}"
      done
    fi

    # Volume counts from state file
    if [ -f "$STATE_FILE" ]; then
      TOTAL_VOLS="$(jq 'length' "$STATE_FILE" 2>/dev/null || echo 0)"
      ACTIVE_VOLS="$(jq '[.[] | select(.mounts | length > 0)] | length' "$STATE_FILE" 2>/dev/null || echo 0)"
      echo "rclone_vfs_volumes_total ${TOTAL_VOLS}"
      echo "rclone_vfs_volumes_active ${ACTIVE_VOLS}"
    else
      echo "rclone_vfs_volumes_total 0"
      echo "rclone_vfs_volumes_active 0"
    fi

    # Disk space available on cache partition
    AVAIL_KB="$(df -k /state 2>/dev/null | tail -1 | awk '{print $4}')"
    case "$AVAIL_KB" in
      ''|*[!0-9]*) ;;
      *) echo "rclone_vfs_cache_available_bytes $((AVAIL_KB * 1024))" ;;
    esac

    # Plugin health (from last probe)
    echo "rclone_vfs_plugin_healthy ${RCLONE_LAST_PROBE_OK}"

  } > "$TMP_PROM"

  # Make readable by node-exporter (runs non-root)
  chmod 644 "$TMP_PROM"
  # Clean stale temp files from prior crashes
  find "$METRICS_DIR" -name '.rclone_vfs_cache.prom.*' -mmin +2 -delete 2>/dev/null
  # Atomic replace
  mv -f "$TMP_PROM" "$PROM_FILE" 2>/dev/null || { rm -f "$TMP_PROM"; return 0; }
  log DEBUG "Metrics written to $PROM_FILE"
}

###############################################################################
# 🔁 MAIN LOOP
###############################################################################
log INFO "Starting loop ♾️"

rclone_fix_tick() {
  log INFO "Tick (next check in ${RCLONE_FIX_INTERVAL}s)"

  if ! plugin_exists; then
    log ERROR "Plugin '$RCLONE_PLUGIN_NAME' not found"
    return 0
  fi

  if ! plugin_enabled; then
    log WARN "Plugin is disabled - recovering disabled plugin"
    recover_disabled_plugin || log ERROR "Disabled plugin recovery failed; will retry next cycle"
    return 0
  fi

  if probe_driver; then
    RCLONE_LAST_PROBE_OK=1
    log INFO "rclone OK (driver reachable)"
    if recover_timed_out_mounted_volumes; then
      # Single reconciliation pass - replaces standalone reconcile_stale_mounts
      # and absorbs missing-volume / wrong-driver / wrong-label cases uniformly.
      reconcile_volumes
    else
      RCLONE_LAST_PROBE_OK=0
      log ERROR "Per-volume rclone health check failed; skipping reconciliation until next cycle"
    fi
  else
    RCLONE_LAST_PROBE_OK=0
    log WARN "rclone unhealthy (driver probe failed) - repairing"
    repair || log ERROR "Repair attempt failed; will retry next cycle"
    # Intentionally skip reconcile_volumes during distress to avoid amplifying
    # the failure with destroy/recreate cycles against a flaky plugin.
  fi

  collect_metrics
}

if [ "$RCLONE_FIXER_TEST_MODE" = "1" ]; then
  return 0 2>/dev/null || exit 0
fi

while true; do
  rclone_fix_tick
  sleep "$RCLONE_FIX_INTERVAL"
done
