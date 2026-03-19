#!/bin/sh
# Unit tests for create_volume_from_spec in check.sh.
#
# Verifies:
#   1. Correctness of the no-eval implementation.
#   2. Behavioral equivalence with the original eval-based implementation for
#      all valid (safe) inputs.
#   3. Protection against shell injection for hostile option values.
#
# Requires: sh, jq
set -eu

###############################################################################
# Setup
###############################################################################
TMPDIR_TEST="$(mktemp -d /tmp/rclone-check-test.XXXXXX)"
trap 'rm -rf "$TMPDIR_TEST"' EXIT INT TERM

PASS=0
FAIL=0

export CAPTURED="$TMPDIR_TEST/captured"

# Mock docker: write each argument on its own line; terminate each call with ---.
# NOTE: "$@" excludes $0, so the mock records only the arguments (not "docker").
mkdir -p "$TMPDIR_TEST/bin"
cat > "$TMPDIR_TEST/bin/docker" <<'MOCK'
#!/bin/sh
printf '%s\n' "$@" >> "$CAPTURED"
printf -- '---\n' >> "$CAPTURED"
MOCK
chmod +x "$TMPDIR_TEST/bin/docker"
export PATH="$TMPDIR_TEST/bin:$PATH"

###############################################################################
# Test helpers
###############################################################################
ok()   { PASS=$((PASS+1)); printf "  ✅ %s\n" "$1"; }
fail() {
  FAIL=$((FAIL+1))
  printf "  ❌ %s\n" "$1"
  printf "     got:  [%s]\n" "$2"
  printf "     want: [%s]\n" "$3"
}

assert_eq() {
  NAME="$1"; GOT="$2"; WANT="$3"
  if [ "$GOT" = "$WANT" ]; then ok "$NAME"; else fail "$NAME" "$GOT" "$WANT"; fi
}

assert_file_absent() {
  NAME="$1"; FILE="$2"
  if [ ! -f "$FILE" ]; then
    ok "$NAME"
  else
    fail "$NAME" "file '$FILE' was CREATED (injection succeeded!)" "file must NOT exist"
    rm -f "$FILE"
  fi
}

###############################################################################
# Reference implementation: ORIGINAL (eval-based) – used for equivalence check
###############################################################################
create_volume_from_spec_OLD() {
  _VOL="$1"; _DRIVER="$2"; _OPTS_JSON="$3"

  CMD="docker volume create \"$_VOL\" -d \"$_DRIVER\""
  while IFS= read -r KV; do
    [ -n "$KV" ] || continue
    CMD="$CMD -o \"$KV\""
  done <<EOF
$(echo "$_OPTS_JSON" | jq -r 'to_entries[]? | "\(.key)=\(.value|tostring)"')
EOF
  CMD="$CMD >/dev/null 2>&1"
  eval "$CMD"
}

###############################################################################
# NEW implementation (no eval) – the function under test
# (copied verbatim from check.sh so this file is self-contained)
###############################################################################
create_volume_from_spec() {
  VOL="$1"
  DRIVER="$2"
  OPTS_JSON="$3"

  set -- docker volume create "$VOL" -d "$DRIVER"
  while IFS= read -r KV; do
    [ -n "$KV" ] || continue
    set -- "$@" -o "$KV"
  done <<EOF
$(echo "$OPTS_JSON" | jq -r 'to_entries[]? | "\(.key)=\(.value|tostring)"')
EOF

  "$@" >/dev/null 2>&1
}

###############################################################################
# Capture helper: clears log, runs given impl, returns captured args
###############################################################################
capture_new() {
  > "$CAPTURED"
  create_volume_from_spec "$@" 2>/dev/null || true
  cat "$CAPTURED"
}

capture_old() {
  > "$CAPTURED"
  create_volume_from_spec_OLD "$@" 2>/dev/null || true
  cat "$CAPTURED"
}

# expected args string: mock captures each arg on its own line (no "docker" prefix)
args() { printf '%s\n' "$@"; printf -- '---\n'; }

###############################################################################
# Test suite 1 – correctness of NEW implementation
###############################################################################
printf '\n=== Suite 1: correctness of no-eval implementation ===\n\n'

# 1a. No options → no -o flags
GOT="$(capture_new "myvol" "rclone" '{}')"
WANT="$(args volume create myvol -d rclone)"
assert_eq "no options → no -o flags" "$GOT" "$WANT"

# 1b. Single option
GOT="$(capture_new "myvol" "rclone" '{"type":"local"}')"
WANT="$(args volume create myvol -d rclone -o type=local)"
assert_eq "single option → one -o flag" "$GOT" "$WANT"

# 1c. Multiple options
GOT="$(capture_new "myvol" "rclone" '{"type":"sftp","remote":"myremote","path":"/data"}')"
WANT="$(args volume create myvol -d rclone -o type=sftp -o remote=myremote -o path=/data)"
assert_eq "multiple options → multiple -o flags" "$GOT" "$WANT"

# 1d. Volume name with hyphens/underscores
GOT="$(capture_new "my-vol_01" "rclone" '{"type":"local"}')"
WANT="$(args volume create my-vol_01 -d rclone -o type=local)"
assert_eq "volume name with hyphens/underscores" "$GOT" "$WANT"

# 1e. Numeric option value (jq tostring keeps it as string)
GOT="$(capture_new "myvol" "rclone" '{"port":22}')"
WANT="$(args volume create myvol -d rclone -o port=22)"
assert_eq "numeric option value cast to string" "$GOT" "$WANT"

###############################################################################
# Test suite 2 – equivalence with OLD (eval) implementation for safe inputs
###############################################################################
printf '\n=== Suite 2: equivalence with original eval-based implementation ===\n\n'

eq_check() {
  LABEL="$1"; shift
  OLD_OUT="$(capture_old "$@")"
  NEW_OUT="$(capture_new "$@")"
  if [ "$OLD_OUT" = "$NEW_OUT" ]; then
    ok "$LABEL"
  else
    fail "$LABEL" "$NEW_OUT" "$OLD_OUT"
  fi
}

eq_check "empty opts"          "myvol" "rclone" '{}'
eq_check "single option"       "myvol" "rclone" '{"type":"local"}'
eq_check "multiple options"    "myvol" "rclone" '{"type":"sftp","remote":"host","path":"/mnt"}'
eq_check "path with slashes"   "myvol" "rclone" '{"path":"/mnt/data/sub"}'
eq_check "alphanumeric value"  "myvol" "rclone" '{"remote":"myS3Remote"}'

###############################################################################
# Test suite 3 – security: hostile values do NOT cause shell injection
#
# Each test writes a marker FILE if injection succeeds.
# Pass = marker file absent after function call.
###############################################################################
printf '\n=== Suite 3: security – hostile values are passed literally ===\n\n'

MARKER="$TMPDIR_TEST/injection_marker"

# Helper: run capture_new; check that MARKER was NOT created
injection_test() {
  NAME="$1"; shift
  rm -f "$MARKER"
  capture_new "$@" >/dev/null 2>&1 || true
  assert_file_absent "$NAME" "$MARKER"
}

# 3a. Dollar-sign command substitution: $(touch MARKER) must NOT be executed
injection_test \
  'dollar-sign $(…) is NOT evaluated' \
  "myvol" "rclone" \
  "{\"key\":\"\$(touch $MARKER)\"}"

# 3b. Backtick command substitution: `touch MARKER` must NOT be executed
injection_test \
  'backtick command substitution is NOT executed' \
  "myvol" "rclone" \
  "{\"key\":\"\`touch $MARKER\`\"}"

# 3c. Semicolon command chaining: ; touch MARKER must NOT run touch
injection_test \
  'semicolon does NOT chain commands' \
  "myvol" "rclone" \
  "{\"path\":\"/data;touch $MARKER\"}"

# 3d. Shell pipe: | touch MARKER must NOT be interpreted as pipe
injection_test \
  'pipe character is NOT interpreted' \
  "myvol" "rclone" \
  "{\"path\":\"/data|touch $MARKER\"}"

# 3e. Value with spaces: no word-splitting (correct arg count)
GOT="$(capture_new "myvol" "rclone" '{"remote":"my remote name"}')"
WANT="$(args volume create myvol -d rclone -o "remote=my remote name")"
assert_eq "space in value → single argv token (no word-split)" "$GOT" "$WANT"

###############################################################################
# Summary
###############################################################################
printf '\n'
printf '────────────────────────────────────────\n'
printf 'Results: %d passed, %d failed (total %d)\n' "$PASS" "$FAIL" "$((PASS+FAIL))"
printf '────────────────────────────────────────\n'

if [ "$FAIL" -eq 0 ]; then
  printf '🎉 All tests passed.\n'
  exit 0
else
  printf '💥 %d test(s) FAILED.\n' "$FAIL"
  exit 1
fi
