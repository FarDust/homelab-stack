#!/bin/sh
# RED contract tests for the production rclone fixer functions.
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
TEST_ROOT="$(mktemp -d /tmp/rclone-check-test.XXXXXX)"
trap 'rm -rf "$TEST_ROOT"' EXIT INT TERM

PASS=0
FAIL=0
TEST_NUMBER=0

mkdir -p "$TEST_ROOT/bin"
export DOCKER_LOG="$TEST_ROOT/docker.log"
export TIMEOUT_LOG="$TEST_ROOT/timeout.log"
REAL_TIMEOUT="$(command -v timeout)"
export REAL_TIMEOUT
export DOCKER_CONTAINER_IDS="$TEST_ROOT/container-ids"
export DOCKER_INSPECT_JSON="$TEST_ROOT/container-inspect.json"
: > "$DOCKER_LOG"
: > "$TIMEOUT_LOG"
export DOCKER_VOLUME_REF_CONTAINERS="$TEST_ROOT/volume-ref-containers"
: > "$DOCKER_VOLUME_REF_CONTAINERS"
: > "$DOCKER_CONTAINER_IDS"
printf '%s\n' '[]' > "$DOCKER_INSPECT_JSON"

cat > "$TEST_ROOT/bin/docker" <<'MOCK_EOF'
#!/bin/sh
printf '%s\n' "$*" >> "$DOCKER_LOG"
if [ "${DOCKER_HANG_ON_CREATE:-0}" = "1" ] && [ "${1:-} ${2:-}" = "volume create" ]; then
  sleep 10
fi
if [ "${1:-} ${2:-} ${3:-}" = "volume inspect ${DOCKER_HANG_ON_INSPECT_VOLUME:-}" ]; then
  sleep 10
fi
case "${1:-} ${2:-}" in
  'ps -q')
    cat "$DOCKER_CONTAINER_IDS"
    ;;
  'ps -aq')
    cat "$DOCKER_VOLUME_REF_CONTAINERS"
    ;;
  'inspect '*)
    cat "$DOCKER_INSPECT_JSON"
    ;;
  'volume inspect')
    printf '[{"Name":"%s"}]
' "${3:-}"
    ;;
esac
exit 0
MOCK_EOF
chmod +x "$TEST_ROOT/bin/docker"
cat > "$TEST_ROOT/bin/timeout" <<'MOCK_EOF'
#!/bin/sh
printf '%s\n' "$*" >> "$TIMEOUT_LOG"
exec "$REAL_TIMEOUT" "$@"
MOCK_EOF
chmod +x "$TEST_ROOT/bin/timeout"
PATH="$TEST_ROOT/bin:$PATH"
export PATH

RCLONE_FIXER_TEST_MODE=1
RCLONE_FIX_LOG_LEVEL=ERROR
RCLONE_RECONCILE_STATE_DIR="$TEST_ROOT/reconcile"
export RCLONE_FIXER_TEST_MODE RCLONE_FIX_LOG_LEVEL RCLONE_RECONCILE_STATE_DIR

# shellcheck source=check.sh
. "$SCRIPT_DIR/check.sh"

require_eq() {
  ACTUAL_VALUE="$1"
  EXPECTED_VALUE="$2"
  REQUIRE_MESSAGE="$3"
  if [ "$ACTUAL_VALUE" != "$EXPECTED_VALUE" ]; then
    printf '    %s\n' "$REQUIRE_MESSAGE"
    printf '    got:  %s\n' "$ACTUAL_VALUE"
    printf '    want: %s\n' "$EXPECTED_VALUE"
    return 1
  fi
}

require_file_absent() {
  REQUIRE_PATH="$1"
  REQUIRE_MESSAGE="$2"
  if [ -e "$REQUIRE_PATH" ]; then
    printf '    %s: %s exists\n' "$REQUIRE_MESSAGE" "$REQUIRE_PATH"
    return 1
  fi
}

run_test() {
  TEST_NAME="$1"
  TEST_FUNCTION="$2"
  TEST_NUMBER=$((TEST_NUMBER + 1))
  TEST_OUTPUT="$TEST_ROOT/test-$TEST_NUMBER.out"
  if ( "$TEST_FUNCTION" ) > "$TEST_OUTPUT" 2>&1; then
    PASS=$((PASS + 1))
    printf 'ok %d - %s\n' "$TEST_NUMBER" "$TEST_NAME"
  else
    FAIL=$((FAIL + 1))
    printf 'not ok %d - %s\n' "$TEST_NUMBER" "$TEST_NAME"
    sed 's/^/  /' "$TEST_OUTPUT"
  fi
}

write_state_fixture() {
  rm -f "$RCLONE_REPAIR_COOLDOWN_FILE"
  rmdir "$RCLONE_REPAIR_LOCK_DIR" 2>/dev/null || true
  CASE_DIR="$(mktemp -d "$TEST_ROOT/state.XXXXXX")"
  STATE_FILE="$CASE_DIR/docker-plugin.state"
  export STATE_FILE
  cat > "$STATE_FILE" <<'STATE_EOF'
[
  {
    "name": "live_volume",
    "mounts": ["opaque-request-A", "opaque-request-B"],
    "path": "remote:live",
    "options": {"uid": 1000},
    "extra": {"preserve": true}
  },
  {
    "name": "stale_volume",
    "mounts": ["opaque-request-Z"],
    "path": "remote:stale",
    "options": {"uid": 2000},
    "extra": {"preserve": true}
  },
  {
    "name": "idle_volume",
    "mounts": [],
    "path": "remote:idle",
    "options": {"uid": 3000},
    "extra": {"preserve": true}
  }
]
STATE_EOF
  printf '%s\n' 'container-123' > "$DOCKER_CONTAINER_IDS"
  cat > "$DOCKER_INSPECT_JSON" <<'INSPECT_EOF'
[
  {
    "Id": "container-123",
    "State": {"Status": "running"},
    "HostConfig": {
      "Mounts": [
        {
          "Type": "volume",
          "Source": "live_volume",
          "VolumeOptions": {
            "DriverConfig": {
              "Name": "rclone",
              "Options": {"type": "gcs", "path": "live"}
            },
            "Labels": {"com.docker.stack.namespace": "main"}
          }
        }
      ]
    }
  }
]
INSPECT_EOF
}

test_real_functions_are_sourced() {
  command -v clean_state_file >/dev/null 2>&1
  command -v repair >/dev/null 2>&1
  command -v create_volume_from_spec >/dev/null 2>&1
}

test_create_volume_uses_safe_argv() {
  : > "$DOCKER_LOG"
  create_volume_from_spec myvol rclone '{"type":"local"}' '{"stack":"main"}'
  require_eq "$(cat "$DOCKER_LOG")" 'volume create myvol -d rclone -o type=local -l stack=main' \
    'production create_volume_from_spec must pass options and labels as discrete argv'
}

test_create_volume_rejects_option_injection() {
  MARKER="$TEST_ROOT/option-injection"
  rm -f "$MARKER"
  create_volume_from_spec myvol rclone "{\"path\":\"\$(touch $MARKER)\"}" '{}'
  require_file_absent "$MARKER" 'option command substitution was executed'
}

test_create_volume_rejects_label_injection() {
  MARKER="$TEST_ROOT/label-injection"
  rm -f "$MARKER"
  create_volume_from_spec myvol rclone '{}' "{\"owner\":\"x; touch $MARKER\"}"
  require_file_absent "$MARKER" 'label shell syntax was executed'
}

test_live_desired_volume_retains_mounts() {
  write_state_fixture
  clean_state_file
  require_eq "$(jq -c '.[] | select(.name == "live_volume") | .mounts' "$STATE_FILE")" \
    '["opaque-request-A","opaque-request-B"]' \
    'live desired volume lost opaque mount request IDs; ownership must be by volume name'
}

test_absent_desired_volume_clears_mounts() {
  write_state_fixture
  clean_state_file
  require_eq "$(jq -c '.[] | select(.name == "stale_volume") | .mounts' "$STATE_FILE")" '[]' \
    'state volume absent from running/created rclone specs must have mounts cleared'
}

test_cleanup_is_selective_not_broad() {
  write_state_fixture
  clean_state_file
  require_eq "$(jq '[.[] | select(.mounts | length > 0)] | map(.name)' "$STATE_FILE" | jq -c .)" \
    '["live_volume"]' \
    'cleanup cleared mounts broadly instead of only stale volume names'
}

test_invalid_json_is_unchanged_without_replacement() {
  CASE_DIR="$(mktemp -d "$TEST_ROOT/invalid.XXXXXX")"
  STATE_FILE="$CASE_DIR/docker-plugin.state"
  export STATE_FILE
  printf '%s\n' '{not-json' > "$STATE_FILE"
  BEFORE_HASH="$(sha256sum "$STATE_FILE" | awk '{print $1}')"
  BEFORE_INODE="$(stat -c %i "$STATE_FILE")"
  if clean_state_file; then
    printf '    invalid JSON cleanup unexpectedly succeeded\n'
    return 1
  fi
  require_eq "$(sha256sum "$STATE_FILE" | awk '{print $1}')" "$BEFORE_HASH" \
    'invalid JSON changed original bytes'
  require_eq "$(stat -c %i "$STATE_FILE")" "$BEFORE_INODE" \
    'invalid JSON replaced the original inode'
  if find "$CASE_DIR" -type f ! -name docker-plugin.state | grep -q .; then
    printf '    invalid JSON created a backup or replacement artifact\n'
    return 1
  fi
}

test_full_backup_precedes_rewrite() {
  write_state_fixture
  ORIGINAL_COPY="$CASE_DIR/original.bytes"
  cp "$STATE_FILE" "$ORIGINAL_COPY"
  clean_state_file
  BACKUP_FILE="$(find "$CASE_DIR" -maxdepth 1 -type f -name 'docker-plugin.state.bak.*' | head -n 1)"
  if [ -z "$BACKUP_FILE" ]; then
    printf '    no full state backup was created before rewrite\n'
    return 1
  fi
  cmp -s "$ORIGINAL_COPY" "$BACKUP_FILE" || {
    printf '    backup is not byte-identical to the pre-rewrite state\n'
    return 1
  }
}

test_state_rewrite_is_atomic() {
  write_state_fixture
  BEFORE_INODE="$(stat -c %i "$STATE_FILE")"
  clean_state_file
  AFTER_INODE="$(stat -c %i "$STATE_FILE")"
  if [ "$BEFORE_INODE" = "$AFTER_INODE" ]; then
    printf '    state file inode did not change; rewrite was not an atomic replacement\n'
    return 1
  fi
}

test_state_rewrite_preserves_mode() {
  write_state_fixture
  chmod 640 "$STATE_FILE"
  clean_state_file
  require_eq "$(stat -c %a "$STATE_FILE")" '640' 'state rewrite changed file mode'
}

test_non_mount_fields_remain_identical() {
  write_state_fixture
  BEFORE_NORMALIZED="$CASE_DIR/before.normalized"
  AFTER_NORMALIZED="$CASE_DIR/after.normalized"
  jq -S 'map(del(.mounts))' "$STATE_FILE" > "$BEFORE_NORMALIZED"
  clean_state_file
  jq -S 'map(del(.mounts))' "$STATE_FILE" > "$AFTER_NORMALIZED"
  cmp -s "$BEFORE_NORMALIZED" "$AFTER_NORMALIZED" || {
    printf '    normalized non-mount fields changed during cleanup\n'
    return 1
  }
}

test_repair_reprobes_before_destructive_cleanup() {
  EVENT_LOG="$TEST_ROOT/repair-order.events"
  : > "$EVENT_LOG"
  : > "$DOCKER_LOG"
  clean_state_file() { printf '%s\n' clean >> "$EVENT_LOG"; return 0; }
  probe_driver() { printf '%s\n' probe >> "$EVENT_LOG"; return 0; }
  repair || true
  cat "$DOCKER_LOG" "$EVENT_LOG" > "$TEST_ROOT/repair-order.all"
  if grep -Fq 'plugin disable -f' "$TEST_ROOT/repair-order.all" || grep -Fxq clean "$EVENT_LOG"; then
    printf '    destructive cleanup ran before a non-destructive restart/reprobe could recover\n'
    cat "$TEST_ROOT/repair-order.all"
    return 1
  fi
  grep -Fxq probe "$EVENT_LOG"
}

test_destructive_repair_requires_stale_state() {
  CASE_DIR="$(mktemp -d "$TEST_ROOT/no-stale.XXXXXX")"
  STATE_FILE="$CASE_DIR/docker-plugin.state"
  export STATE_FILE
  printf '%s\n' '[]' > "$STATE_FILE"
  : > "$DOCKER_CONTAINER_IDS"
  printf '%s\n' '[]' > "$DOCKER_INSPECT_JSON"
  : > "$DOCKER_LOG"
  probe_driver() { return 1; }
  repair || true
  if grep -Fq 'plugin disable -f' "$DOCKER_LOG"; then
    printf '    destructive tier ran without any stale state ownership\n'
    cat "$DOCKER_LOG"
    return 1
  fi
}


test_disabled_plugin_recovery_enables_after_state_cleanup_without_stale_mounts() {
  CASE_DIR="$(mktemp -d "$TEST_ROOT/disabled-plugin.XXXXXX")"
  STATE_FILE="$CASE_DIR/docker-plugin.state"
  export STATE_FILE
  printf '%s\n' '[]' > "$STATE_FILE"
  : > "$DOCKER_CONTAINER_IDS"
  printf '%s\n' '[]' > "$DOCKER_INSPECT_JSON"
  : > "$DOCKER_LOG"
  probe_driver() { return 0; }
  recover_disabled_plugin
  grep -Fq 'plugin enable --timeout 300 rclone' "$DOCKER_LOG" || {
    printf '    disabled-plugin recovery did not enable the rclone plugin\n'
    cat "$DOCKER_LOG"
    return 1
  }
  find "$CASE_DIR" -maxdepth 1 -type f -name 'docker-plugin.state.bak.*' | grep -q . || {
    printf '    disabled-plugin recovery did not create a state-file backup before rewrite\n'
    return 1
  }
}


test_disabled_plugin_recovery_fails_closed_on_state_cleanup_error() {
  : > "$DOCKER_LOG"
  clean_state_file() { return 1; }
  enable_plugin_bounded() {
    printf '%s\n' enable >> "$DOCKER_LOG"
    return 0
  }
  probe_driver() {
    printf '%s\n' probe >> "$DOCKER_LOG"
    return 0
  }
  if recover_disabled_plugin; then
    printf '    disabled-plugin recovery succeeded after cleanup failure\n'
    return 1
  fi
  if grep -Eq '^(enable|probe)$' "$DOCKER_LOG"; then
    printf '    disabled-plugin recovery continued after cleanup failure\n'
    cat "$DOCKER_LOG"
    return 1
  fi
}

test_disabled_plugin_tick_uses_disabled_recovery_not_generic_repair() {
  : > "$DOCKER_LOG"
  plugin_exists() { return 0; }
  plugin_enabled() { return 1; }
  recover_disabled_plugin() {
    printf '%s\n' recover-disabled >> "$DOCKER_LOG"
    return 0
  }
  repair() {
    printf '%s\n' generic-repair >> "$DOCKER_LOG"
    return 0
  }
  probe_driver() {
    printf '%s\n' probe >> "$DOCKER_LOG"
    return 0
  }
  collect_metrics() { printf '%s\n' metrics >> "$DOCKER_LOG"; }
  rclone_fix_tick
  grep -Fxq recover-disabled "$DOCKER_LOG" || {
    printf '    disabled-plugin tick did not call recover_disabled_plugin\n'
    cat "$DOCKER_LOG"
    return 1
  }
  if grep -Fxq generic-repair "$DOCKER_LOG"; then
    printf '    disabled-plugin tick called generic repair instead of disabled recovery\n'
    cat "$DOCKER_LOG"
    return 1
  fi
}

test_enable_helper_propagates_docker_timeout_with_shutdown_margin() {
  : > "$DOCKER_LOG"
  : > "$TIMEOUT_LOG"
  RCLONE_ENABLE_TIMEOUT_SECONDS=300
  RCLONE_PLUGIN_NAME=rclone
  export RCLONE_ENABLE_TIMEOUT_SECONDS RCLONE_PLUGIN_NAME
  enable_plugin_bounded
  require_eq "$(cat "$TIMEOUT_LOG")" '330 docker plugin enable --timeout 300 rclone' \
    'enable helper must allow Docker HTTP timeout plus a 30-second bounded shutdown margin'
  require_eq "$(cat "$DOCKER_LOG")" 'plugin enable --timeout 300 rclone' \
    'enable helper must pass the validated timeout to Docker plugin enable'
}

test_non_destructive_repair_routes_enable_through_bounded_helper() {
  EVENT_LOG="$TEST_ROOT/non-destructive-enable.events"
  : > "$EVENT_LOG"
  enable_plugin_bounded() { printf '%s\n' bounded-enable >> "$EVENT_LOG"; return 0; }
  probe_driver() { return 0; }
  repair
  require_eq "$(grep -c '^bounded-enable$' "$EVENT_LOG" || true)" '1' \
    'non-destructive repair bypassed enable_plugin_bounded'
}

test_destructive_repair_routes_every_enable_through_bounded_helper() {
  EVENT_LOG="$TEST_ROOT/destructive-enable.events"
  : > "$EVENT_LOG"
  rm -f "$RCLONE_REPAIR_COOLDOWN_FILE"
  rmdir "$RCLONE_REPAIR_LOCK_DIR" 2>/dev/null || true
  RCLONE_REPAIR_COOLDOWN_SECONDS=0
  export RCLONE_REPAIR_COOLDOWN_SECONDS
  enable_plugin_bounded() { printf '%s\n' bounded-enable >> "$EVENT_LOG"; return 0; }
  probe_driver() { return 1; }
  stale_state_exists() { return 0; }
  clean_state_file() { return 0; }
  repair || true
  require_eq "$(grep -c '^bounded-enable$' "$EVENT_LOG" || true)" '2' \
    'repair tiers bypassed enable_plugin_bounded'
}

test_destructive_repair_uses_exclusive_lock() {
  write_state_fixture
  RCLONE_REPAIR_COOLDOWN_SECONDS=0
  export RCLONE_REPAIR_COOLDOWN_SECONDS
  EVENT_LOG="$TEST_ROOT/repair-lock.events"
  : > "$EVENT_LOG"
  : > "$DOCKER_LOG"
  clean_state_file() {
    printf '%s\n' clean >> "$EVENT_LOG"
    sleep 1
    return 0
  }
  probe_driver() { return 1; }
  ( repair || true ) &
  FIRST_PID=$!
  ( repair || true ) &
  SECOND_PID=$!
  wait "$FIRST_PID"
  wait "$SECOND_PID"
  require_eq "$(grep -c '^clean$' "$EVENT_LOG" || true)" '1' \
    'concurrent repair calls both entered destructive state cleanup'
}

test_destructive_repair_honors_cooldown() {
  write_state_fixture
  EVENT_LOG="$TEST_ROOT/repair-cooldown.events"
  : > "$EVENT_LOG"
  : > "$DOCKER_LOG"
  clean_state_file() { printf '%s\n' clean >> "$EVENT_LOG"; return 0; }
  probe_driver() { return 1; }
  repair || true
  repair || true
  require_eq "$(grep -c '^clean$' "$EVENT_LOG" || true)" '1' \
    'immediate repeated repair re-entered destructive cleanup during cooldown'
}

test_probe_driver_bounds_hung_create() {
  : > "$DOCKER_LOG"
  DOCKER_HANG_ON_CREATE=1
  RCLONE_PROBE_TIMEOUT_SECONDS=1
  export DOCKER_HANG_ON_CREATE RCLONE_PROBE_TIMEOUT_SECONDS
  START_SECONDS="$(date +%s)"
  if probe_driver; then
    printf '    hung probe unexpectedly succeeded\n'
    return 1
  fi
  ELAPSED_SECONDS=$(( $(date +%s) - START_SECONDS ))
  if [ "$ELAPSED_SECONDS" -gt 3 ]; then
    printf '    hung docker volume create blocked for %ss; configured timeout was %ss\n' \
      "$ELAPSED_SECONDS" "$RCLONE_PROBE_TIMEOUT_SECONDS"
    return 1
  fi
  grep -Fq 'volume create __rclone_probe__' "$DOCKER_LOG"
}

test_healthy_rclone_label_drift_is_non_destructive() {
  DESTROY_MARKER="$TEST_ROOT/label-drift-destroyed"
  rm -f "$DESTROY_MARKER"
  derive_desired_volumes() {
    printf '%s\t%s\t%s\t%s\n' \
      stable_volume rclone '{}' '{"com.docker.stack.namespace":"main"}'
  }
  get_actual_volume() {
    printf '%s\t%s\t%s\t%s\n' rclone '{}' '{}' /mnt/stable_volume
  }
  destroy_volume_safely() {
    : > "$DESTROY_MARKER"
    return 0
  }
  create_volume_from_spec() { return 0; }

  reconcile_volumes

  require_file_absent "$DESTROY_MARKER" \
    'healthy rclone volume was destroyed for label-only drift'
}

write_per_volume_state_fixture() {
  rm -f "$RCLONE_REPAIR_COOLDOWN_FILE"
  rmdir "$RCLONE_REPAIR_LOCK_DIR" 2>/dev/null || true
  CASE_DIR="$(mktemp -d "$TEST_ROOT/per-volume.XXXXXX")"
  STATE_FILE="$CASE_DIR/docker-plugin.state"
  export STATE_FILE
  cat > "$STATE_FILE" <<'STATE_EOF'
[
  {
    "name": "llms-governance_open_webui_data",
    "mounts": ["f3892499c062cdb576a66e0417356bf109ab1b7226cf559110c772be14d6f807"],
    "path": "gcs:example-swarm-storage/open_web_ui/data",
    "options": {"allow_other": "true", "vfs_cache_mode": "full"},
    "labels": {"com.docker.stack.namespace": "llms-governance"}
  },
  {
    "name": "other_active_volume",
    "mounts": ["opaque-other-mount"],
    "path": "remote:other",
    "options": {"keep": "true"},
    "labels": {"com.docker.stack.namespace": "other"}
  }
]
STATE_EOF
  : > "$DOCKER_LOG"
  : > "$DOCKER_VOLUME_REF_CONTAINERS"
}

test_bounded_volume_get_bounds_hung_inspect() {
  : > "$DOCKER_LOG"
  DOCKER_HANG_ON_INSPECT_VOLUME=llms-governance_open_webui_data
  RCLONE_PROBE_TIMEOUT_SECONDS=1
  export DOCKER_HANG_ON_INSPECT_VOLUME RCLONE_PROBE_TIMEOUT_SECONDS
  START_SECONDS="$(date +%s)"
  if bounded_volume_get llms-governance_open_webui_data; then
    printf '    hung volume inspect unexpectedly succeeded\n'
    return 1
  fi
  ELAPSED_SECONDS=$(( $(date +%s) - START_SECONDS ))
  if [ "$ELAPSED_SECONDS" -gt 3 ]; then
    printf '    hung docker volume inspect blocked for %ss; configured timeout was %ss\n' \
      "$ELAPSED_SECONDS" "$RCLONE_PROBE_TIMEOUT_SECONDS"
    return 1
  fi
  grep -Fq 'volume inspect llms-governance_open_webui_data' "$DOCKER_LOG"
}

test_stale_mounted_volume_recovery_clears_only_target() {
  write_per_volume_state_fixture
  bounded_volume_get() { return 0; }
  recover_stale_mounted_volume llms-governance_open_webui_data
  require_eq "$(jq -c '.[] | select(.name == "llms-governance_open_webui_data") | .mounts' "$STATE_FILE")" '[]' \
    'target timed-out volume mounts were not cleared'
  require_eq "$(jq -c '.[] | select(.name == "other_active_volume") | .mounts' "$STATE_FILE")" '["opaque-other-mount"]' \
    'unrelated mounted volume was modified'
  find "$CASE_DIR" -maxdepth 1 -type f -name 'docker-plugin.state.bak.*' | grep -q . || {
    printf '    targeted recovery did not create a full state backup\n'
    return 1
  }
  grep -Fq 'plugin disable rclone' "$DOCKER_LOG" || {
    printf '    targeted recovery did not reload the rclone plugin\n'
    cat "$DOCKER_LOG"
    return 1
  }
  if grep -Eq 'volume rm|service update|node update|systemctl|restart docker' "$DOCKER_LOG"; then
    printf '    targeted recovery used a prohibited broad operation\n'
    cat "$DOCKER_LOG"
    return 1
  fi
}

test_stale_mounted_volume_recovery_requires_matching_mounts() {
  write_per_volume_state_fixture
  if recover_stale_mounted_volume missing_volume; then
    printf '    recovery succeeded without a matching mounted state entry\n'
    return 1
  fi
  if find "$CASE_DIR" -maxdepth 1 -type f -name 'docker-plugin.state.bak.*' | grep -q .; then
    printf '    recovery created backup despite no matching mounted state entry\n'
    return 1
  fi
}

test_stale_mounted_volume_recovery_refuses_local_container_refs() {
  write_per_volume_state_fixture
  printf '%s\n' 'container-using-volume' > "$DOCKER_VOLUME_REF_CONTAINERS"
  if recover_stale_mounted_volume llms-governance_open_webui_data; then
    printf '    recovery succeeded while a local container referenced the volume\n'
    return 1
  fi
  require_eq "$(jq -c '.[] | select(.name == "llms-governance_open_webui_data") | .mounts' "$STATE_FILE")" \
    '["f3892499c062cdb576a66e0417356bf109ab1b7226cf559110c772be14d6f807"]' \
    'recovery modified state while local container refs existed'
}

test_tick_checks_mounted_state_volumes_after_green_global_probe() {
  : > "$DOCKER_LOG"
  plugin_exists() { return 0; }
  plugin_enabled() { return 0; }
  probe_driver() { return 0; }
  recover_timed_out_mounted_volumes() {
    printf '%s\n' mounted-volume-check >> "$DOCKER_LOG"
    return 1
  }
  reconcile_volumes() {
    printf '%s\n' reconcile >> "$DOCKER_LOG"
    return 0
  }
  collect_metrics() { printf '%s\n' metrics >> "$DOCKER_LOG"; }
  rclone_fix_tick
  grep -Fxq mounted-volume-check "$DOCKER_LOG" || {
    printf '    tick did not check persisted mounted volumes after global probe success\n'
    cat "$DOCKER_LOG"
    return 1
  }
  if grep -Fxq reconcile "$DOCKER_LOG"; then
    printf '    tick reconciled volumes after per-volume health check failed\n'
    cat "$DOCKER_LOG"
    return 1
  fi
}

printf '1..29\n'
run_test 'production functions are sourced in test mode' test_real_functions_are_sourced
run_test 'create_volume_from_spec uses safe argv for options and labels' test_create_volume_uses_safe_argv
run_test 'create_volume_from_spec blocks option-value injection' test_create_volume_rejects_option_injection
run_test 'create_volume_from_spec blocks label-value injection' test_create_volume_rejects_label_injection
run_test 'live desired volume retains opaque mount request IDs' test_live_desired_volume_retains_mounts
run_test 'state volume absent from desired set has mounts cleared' test_absent_desired_volume_clears_mounts
run_test 'state cleanup is selective and never broad' test_cleanup_is_selective_not_broad
run_test 'invalid JSON remains byte-identical with no replacement' test_invalid_json_is_unchanged_without_replacement
run_test 'full byte-identical backup exists before state rewrite' test_full_backup_precedes_rewrite
run_test 'state rewrite uses atomic replacement' test_state_rewrite_is_atomic
run_test 'state rewrite preserves file mode' test_state_rewrite_preserves_mode
run_test 'normalized non-mount fields remain identical' test_non_mount_fields_remain_identical
run_test 'repair performs non-destructive restart/reprobe first' test_repair_reprobes_before_destructive_cleanup
run_test 'destructive repair requires proven stale state' test_destructive_repair_requires_stale_state
run_test 'disabled plugin recovery enables after state cleanup without stale mounts' test_disabled_plugin_recovery_enables_after_state_cleanup_without_stale_mounts
run_test 'disabled plugin recovery fails closed on state cleanup error' test_disabled_plugin_recovery_fails_closed_on_state_cleanup_error
run_test 'disabled plugin tick uses disabled recovery not generic repair' test_disabled_plugin_tick_uses_disabled_recovery_not_generic_repair
run_test 'enable helper propagates Docker timeout with bounded shutdown margin' test_enable_helper_propagates_docker_timeout_with_shutdown_margin
run_test 'non-destructive repair routes enable through bounded helper' test_non_destructive_repair_routes_enable_through_bounded_helper
run_test 'destructive repair routes every enable through bounded helper' test_destructive_repair_routes_every_enable_through_bounded_helper
run_test 'destructive repair requires an exclusive lock' test_destructive_repair_uses_exclusive_lock
run_test 'destructive repair honors cooldown' test_destructive_repair_honors_cooldown
run_test 'plugin probe bounds a hung docker volume create' test_probe_driver_bounds_hung_create
run_test 'healthy rclone label-only drift is non-destructive' test_healthy_rclone_label_drift_is_non_destructive
run_test 'bounded per-volume GET probe bounds a hung inspect' test_bounded_volume_get_bounds_hung_inspect
run_test 'stale mounted volume recovery clears only target' test_stale_mounted_volume_recovery_clears_only_target
run_test 'stale mounted volume recovery requires matching mounts' test_stale_mounted_volume_recovery_requires_matching_mounts
run_test 'stale mounted volume recovery refuses local container refs' test_stale_mounted_volume_recovery_refuses_local_container_refs
run_test 'tick checks mounted state volumes after green global probe' test_tick_checks_mounted_state_volumes_after_green_global_probe

printf '# %d passed, %d failed\n' "$PASS" "$FAIL"
if [ "$FAIL" -ne 0 ]; then
  printf '# RED: current production behavior violates %d safety contract(s)\n' "$FAIL"
  exit 1
fi
printf '# GREEN: all safety contracts pass\n'
exit 0
