#!/bin/sh
set -eu

STATE_DIR="${STATE_DIR:-/state}"
COOLDOWN_SECONDS="${REBALANCE_COOLDOWN_SECONDS:-300}"
EPHEMERAL_LABEL_KEY="${EPHEMERAL_LABEL_KEY:-node.ephemeral}"
FORBID_CONSTRAINT="${EPHEMERAL_FORBID_CONSTRAINT:-node.labels.node.ephemeral != true}"
SKIP_CONSTRAINTS="${REBALANCE_SKIP_CONSTRAINTS:-${FORBID_CONSTRAINT},node.labels.storage.manager == true,node.labels.swarm.leader == true,node.role == manager}"
SELF_SERVICE_NAME="${REBALANCE_SELF_SERVICE:-}"
OTEL_LOGS_ENDPOINT="${OTEL_LOGS_ENDPOINT:-}"
OTEL_SERVICE_NAME="${OTEL_SERVICE_NAME:-ephemeral-rebalance}"
OTEL_INSECURE="${OTEL_INSECURE:-false}"
RCLONE_REJECT_FIX_ENABLED="${RCLONE_REJECT_FIX_ENABLED:-false}"
RCLONE_REJECT_CHECK_INTERVAL="${RCLONE_REJECT_CHECK_INTERVAL:-60}"
RCLONE_REJECT_COOLDOWN_SECONDS="${RCLONE_REJECT_COOLDOWN_SECONDS:-300}"
RCLONE_REJECT_ERROR_PATTERN="${RCLONE_REJECT_ERROR_PATTERN:-rclone}"
REBALANCE_SERVICE_COOLDOWN_SECONDS="${REBALANCE_SERVICE_COOLDOWN_SECONDS:-${COOLDOWN_SECONDS}}"

mkdir -p "${STATE_DIR}/nodes"
mkdir -p "${STATE_DIR}/rejected"
mkdir -p "${STATE_DIR}/services"

log() {
  level="INFO"
  if [ $# -gt 1 ] && echo "$1" | grep -Eq '^(DEBUG|INFO|WARN|ERROR)$'; then
    level="$1"
    shift
  fi
  msg="$*"
  case "$level" in
    DEBUG) emo="🪵" ;;
    INFO) emo="ℹ️" ;;
    WARN) emo="⚠️" ;;
    ERROR) emo="❌" ;;
    *) emo="ℹ️" ;;
  esac
  printf '%s %s %s\n' "$(date -Iseconds)" "$emo" "$msg"
}

json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/\"/\\"/g; s/\t/\\t/g; s/\r/\\r/g; s/\n/\\n/g'
}

send_otel() {
  [ -z "$OTEL_LOGS_ENDPOINT" ] && return 0
  message=$(json_escape "$1")
  timestamp="$(date +%s)000000000"
  payload="{\"resourceLogs\":[{\"resource\":{\"attributes\":[{\"key\":\"service.name\",\"value\":{\"stringValue\":\"${OTEL_SERVICE_NAME}\"}}]},\"scopeLogs\":[{\"scope\":{\"name\":\"ephemeral-rebalance\"},\"logRecords\":[{\"timeUnixNano\":\"${timestamp}\",\"severityText\":\"INFO\",\"body\":{\"stringValue\":\"${message}\"}}]}]}]}"

  if [ "$OTEL_INSECURE" = "true" ]; then
    wget -qO- --no-check-certificate --header='Content-Type: application/json' --post-data="$payload" "$OTEL_LOGS_ENDPOINT" >/dev/null 2>&1 || true
  else
    wget -qO- --header='Content-Type: application/json' --post-data="$payload" "$OTEL_LOGS_ENDPOINT" >/dev/null 2>&1 || true
  fi
}

should_skip_constraints() {
  constraints="$1"
  old_ifs="$IFS"
  IFS=','
  for pattern in $SKIP_CONSTRAINTS; do
    pattern=$(printf '%s' "$pattern" | tr -d '[:space:]')
    [ -z "$pattern" ] && continue
    while IFS= read -r constraint; do
      [ -z "$constraint" ] && continue
      normalized_constraint=$(printf '%s' "$constraint" | tr -d '[:space:]')
      if [ "$normalized_constraint" = "$pattern" ]; then
        IFS="$old_ifs"
        return 0
      fi
    done <<EOF
$constraints
EOF
  done
  IFS="$old_ifs"
  return 1
}

constraints_json_to_lines() {
  constraints_json="$1"
  [ -z "$constraints_json" ] && return 0
  [ "$constraints_json" = "null" ] && return 0
  printf '%s' "$constraints_json" | \
    sed 's/^\[//; s/\]$//' | \
    tr ',' '\n' | \
    sed 's/^ *"//; s/" *$//'
}

service_cooldown_ok() {
  service="$1"
  now=$(date +%s)
  last=$(cat "${STATE_DIR}/services/${service}" 2>/dev/null || echo 0)
  if [ $((now - last)) -lt "$REBALANCE_SERVICE_COOLDOWN_SECONDS" ]; then
    return 1
  fi
  printf '%s\n' "$now" > "${STATE_DIR}/services/${service}"
  return 0
}

service_is_global() {
  docker service inspect --format '{{if .Spec.Mode.Global}}true{{else}}false{{end}}' "$1" 2>/dev/null | grep -q true
}

task_is_healthy() {
  task_id="$1"
  container_id=$(docker inspect --format '{{.Status.ContainerStatus.ContainerID}}' "$task_id" 2>/dev/null || true)
  [ -z "$container_id" ] && return 1
  health=$(docker inspect --format '{{.State.Health.Status}}' "$container_id" 2>/dev/null || true)
  [ "$health" = "healthy" ]
}

init_states() {
  docker node ls -q | while read -r node_id; do
    info=$(docker node inspect --format '{{.Status.State}} {{.Spec.Availability}}' "$node_id" 2>/dev/null || true)
    if [ -n "$info" ]; then
      printf '%s\n' "$info" > "${STATE_DIR}/nodes/${node_id}"
    fi
  done
}

should_trigger() {
  now=$(date +%s)
  last=$(cat "${STATE_DIR}/last_rebalance" 2>/dev/null || echo 0)
  if [ $((now - last)) -lt "$COOLDOWN_SECONDS" ]; then
    return 1
  fi
  printf '%s\n' "$now" > "${STATE_DIR}/last_rebalance"
  return 0
}

reject_cooldown_ok() {
  service="$1"
  now=$(date +%s)
  last=$(cat "${STATE_DIR}/rejected/${service}" 2>/dev/null || echo 0)
  if [ $((now - last)) -lt "$RCLONE_REJECT_COOLDOWN_SECONDS" ]; then
    return 1
  fi
  printf '%s\n' "$now" > "${STATE_DIR}/rejected/${service}"
  return 0
}

handle_rejected_service() {
  service="$1"
  task_id="$2"
  error="$3"

  if [ -n "$SELF_SERVICE_NAME" ] && [ "$service" = "$SELF_SERVICE_NAME" ]; then
    return 0
  fi

  if service_is_global "$service"; then
    message="Skipping rejected-task rebalance for global service ${service}."
    log INFO "$message"
    send_otel "$message"
    return 0
  fi

  if task_is_healthy "$task_id"; then
    message="Task healthy; skipping rejected-task rebalance for ${service} (${task_id})."
    log INFO "$message"
    send_otel "$message"
    return 0
  fi

  if ! reject_cooldown_ok "$service"; then
    message="Cooldown active; skipping rejected-task rebalance for ${service}."
    log INFO "$message"
    send_otel "$message"
    return 0
  fi

  message="Rejected task detected (rclone) for ${service} (${task_id}). Forcing update."
  log WARN "$message"
  send_otel "$message"

  if docker service update --force --detach "$service" >/dev/null 2>&1; then
    message="Rebalance update triggered after rejection: ${service}"
    log INFO "$message"
    send_otel "$message"
  else
    message="Rebalance update failed after rejection: ${service}"
    log ERROR "$message"
    send_otel "$message"
  fi
}

scan_rejected_tasks() {
  services=$(docker service ls --format '{{.Name}}')
  [ -z "$services" ] && return 0

  echo "$services" | while read -r service; do
    [ -z "$service" ] && continue

    docker service ps --no-trunc --format '{{.CurrentState}}|{{.Error}}|{{.ID}}' "$service" 2>/dev/null | \
      while IFS='|' read -r state error task_id; do
        case "$state" in
          Rejected*|Failed*)
            if echo "$error" | grep -qiE "$RCLONE_REJECT_ERROR_PATTERN"; then
              handle_rejected_service "$service" "$task_id" "$error"
              break
            fi
            ;;
        esac
      done
  done
}

rejected_task_loop() {
  if [ "$RCLONE_REJECT_FIX_ENABLED" != "true" ]; then
    log INFO "Rejected-task rebalance disabled (RCLONE_REJECT_FIX_ENABLED=$RCLONE_REJECT_FIX_ENABLED)."
    return 0
  fi

  log INFO "Watching for rejected tasks matching pattern: ${RCLONE_REJECT_ERROR_PATTERN}"
  send_otel "Watching for rejected tasks matching pattern: ${RCLONE_REJECT_ERROR_PATTERN}"

  while true; do
    scan_rejected_tasks
    sleep "$RCLONE_REJECT_CHECK_INTERVAL"
  done
}

rebalance_services() {
  services=$(docker service ls --format '{{.Name}}')
  if [ -z "$services" ]; then
    log INFO "No services found to rebalance."
    return 0
  fi

  message="Triggering rebalance across eligible services."
  log INFO "$message"
  send_otel "$message"
  echo "$services" | while read -r service; do
    [ -z "$service" ] && continue
    if [ -n "$SELF_SERVICE_NAME" ] && [ "$service" = "$SELF_SERVICE_NAME" ]; then
      message="Skipping self service: ${service}"
      log DEBUG "$message"
      continue
    fi

    constraints_json=$(docker service inspect --format '{{json .Spec.TaskTemplate.Placement.Constraints}}' "$service" 2>/dev/null || echo "")
    constraints=$(constraints_json_to_lines "$constraints_json" || true)
    if [ -n "$constraints" ] && should_skip_constraints "$constraints"; then
      message="Skipping service by cluster-group constraints: ${service}"
      log INFO "$message"
      send_otel "$message"
      continue
    fi

    if ! service_cooldown_ok "$service"; then
      message="Skipping service due to per-service cooldown: ${service}"
      log INFO "$message"
      send_otel "$message"
      continue
    fi

    if docker service update --force --detach "$service" >/dev/null 2>&1; then
      message="Rebalance update triggered: ${service}"
      log INFO "$message"
      send_otel "$message"
    else
      message="Rebalance update failed: ${service}"
      log WARN "$message"
      send_otel "$message"
    fi
  done
}

handle_node_update() {
  node_id="$1"
  info=$(docker node inspect --format '{{.Status.State}} {{.Spec.Availability}} {{index .Spec.Labels "'"${EPHEMERAL_LABEL_KEY}"'"}} {{.Description.Hostname}}' "$node_id" 2>/dev/null || true)
  if [ -z "$info" ]; then
    return
  fi

  set -- $info
  state="$1"
  availability="$2"
  ephemeral="${3:-}"
  hostname="${4:-}"

  prev=$(cat "${STATE_DIR}/nodes/${node_id}" 2>/dev/null || echo "")
  printf '%s %s\n' "$state" "$availability" > "${STATE_DIR}/nodes/${node_id}"

  if [ "$ephemeral" != "true" ]; then
    return
  fi

  if [ "$state" = "ready" ] && [ "$availability" = "active" ] && [ "$prev" != "ready active" ]; then
    message="Ephemeral node active: ${hostname:-$node_id}"
    log INFO "$message"
    send_otel "$message"
    if should_trigger; then
      rebalance_services
    else
      message="Cooldown active; skipping rebalance."
      log INFO "$message"
      send_otel "$message"
    fi
    return
  fi

  if [ "$prev" = "ready active" ] && { [ "$state" != "ready" ] || [ "$availability" != "active" ]; }; then
    message="Ephemeral node inactive: ${hostname:-$node_id} (state=${state}, availability=${availability})"
    log INFO "$message"
    send_otel "$message"
    if should_trigger; then
      rebalance_services
    else
      message="Cooldown active; skipping rebalance."
      log INFO "$message"
      send_otel "$message"
    fi
  fi
}

init_states
log INFO "Watching for ephemeral node activations."
send_otel "Watching for ephemeral node activations."

# Optional rejected-task watcher
rejected_task_loop &

# Event-driven loop for node updates
# Using scope=swarm to avoid local-only events.
docker system events --filter scope=swarm --filter type=node --filter event=update --format '{{.Actor.ID}}' | while read -r node_id; do
  [ -z "$node_id" ] && continue
  handle_node_update "$node_id"
done
