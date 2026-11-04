#!/usr/bin/env bash
set -euo pipefail

ROOT=${CERT_WATCH_TEST_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
WATCHER="$ROOT/stacks/main/configs/postgres/cert-watch.sh"
BOOTSTRAP="$ROOT/stacks/main/configs/postgres/pgvector-bootstrap.sh"
STORAGE="$ROOT/stacks/main/storage.yml"


fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

assert_literal() {
    local file=$1
    local text=$2
    grep -Fq -- "$text" "$file" || fail "missing literal '$text' in $file"
}

assert_matches() {
    local file=$1
    local pattern=$2
    grep -Eq -- "$pattern" "$file" || fail "missing pattern '$pattern' in $file"
}

assert_not_matches() {
    local file=$1
    local pattern=$2
    if grep -Eq -- "$pattern" "$file"; then
        fail "forbidden pattern '$pattern' in $file"
    fi
}

assert_count_at_least() {
    local file=$1
    local pattern=$2
    local minimum=$3
    local count
    count=$(grep -Ec -- "$pattern" "$file" || true)
    [ "$count" -ge "$minimum" ] || fail "pattern '$pattern' appears $count times in $file, expected at least $minimum"
}

assert_status_zero() {
    local case_name=$1
    [ "$LAST_STATUS" -eq 0 ] || {
        printf 'OUTPUT (%s):\n' "$case_name" >&2
        cat "$run_log" >&2 || true
        fail "$case_name returned status $LAST_STATUS"
    }
}

assert_hash_equal() {
    local expected_file=$1
    local actual_file=$2
    local expected_hash
    local actual_hash
    expected_hash=$(sha256sum "$expected_file" | awk '{print $1}')
    actual_hash=$(sha256sum "$actual_file" | awk '{print $1}')
    [ "$expected_hash" = "$actual_hash" ] || fail "hash mismatch: expected $expected_file, got $actual_file"
}

assert_mode() {
    local file=$1
    local expected=$2
    local actual
    actual=$(stat -c '%a' "$file")
    [ "$actual" = "$expected" ] || fail "mode mismatch: $file expected=$expected actual=$actual"
}

assert_owner() {
    local file=$1
    local expected=$2
    local actual
    actual=$(stat -c '%u:%g' "$file")
    [ "$actual" = "$expected" ] || fail "owner mismatch: $file expected=$expected actual=$actual"
}

assert_reload_count() {
    local expected=$1
    local actual
    actual=$(wc -l < "$reload_count")
    [ "$actual" = "$expected" ] || fail "reload count mismatch: expected=$expected actual=$actual"
}

assert_no_pending() {
    [ ! -e "$target_dir/.cert-watch.pending" ] || fail "pending marker remains in $target_dir"
}

assert_target_clean() {
    local leftover
    leftover=$(find "$target_dir" -mindepth 1 -maxdepth 1 \
        ! -name fullchain.pem ! -name privkey.pem ! -name .cert-watch.pending \
        -print -quit)
    [ -z "$leftover" ] || fail "staging artifact remains: $leftover"
}

case_start() {
    printf 'Given %s\n' "$1"
    printf 'When %s\n' "$2"
    printf 'Then %s\n' "$3"
}


if [ ! -f "$WATCHER" ]; then
    printf 'FIXTURE_PHASE=not_started\n'
    fail "watcher missing: $WATCHER"
fi

[ -x "$WATCHER" ] || fail "watcher is not executable: $WATCHER"
sh -n "$WATCHER" || fail "watcher is not valid POSIX sh: $WATCHER"
assert_literal "$WATCHER" 'gosu postgres'
assert_literal "$WATCHER" '/usr/lib/postgresql/17/bin/pg_ctl'
assert_literal "$WATCHER" '/var/lib/postgresql/17/main'
assert_not_matches "$WATCHER" '(^|[^[:alnum:]_])docker([[:space:]]|$)|docker\.sock'
assert_not_matches "$WATCHER" '(/proc/1|--pid[[:space:]=]+host|host[_-]pid)'
assert_not_matches "$WATCHER" 'pg_reload_conf'
assert_not_matches "$WATCHER" '(^|[^[:alnum:]_])eval([^[:alnum:]_]|$)'
assert_not_matches "$WATCHER" '(POSTGRES_PASSWORD|PGPASSWORD|DATABASE_URL|password[[:space:]]*=|credential|secret)'
assert_literal "$WATCHER" 'source_cert=${CERT_WATCH_SOURCE_CERT:-/lego/fullchain.pem}'
assert_literal "$WATCHER" 'source_key=${CERT_WATCH_SOURCE_KEY:-/lego/privkey.pem}'
assert_literal "$WATCHER" 'CERT_WATCH_TEST_MODE'
assert_not_matches "$WATCHER" 'CERT_WATCH_PG_CTL'
assert_matches "$WATCHER" 'printf[[:space:]].*&2'

sh -n "$BOOTSTRAP" || fail "bootstrap is not valid POSIX sh: $BOOTSTRAP"
assert_literal "$BOOTSTRAP" 'cert-watch.sh'
assert_literal "$BOOTSTRAP" 'trap'
assert_matches "$BOOTSTRAP" 'trap[[:space:]].*(TERM|INT)'
assert_matches "$BOOTSTRAP" 'watcher_pid'
assert_matches "$BOOTSTRAP" 'upstream_pid'
assert_matches "$BOOTSTRAP" 'kill[[:space:]].*watcher_pid'
assert_matches "$BOOTSTRAP" 'kill[[:space:]].*upstream_pid'
assert_matches "$BOOTSTRAP" 'wait[[:space:]].*watcher_pid'
assert_matches "$BOOTSTRAP" 'wait[[:space:]].*upstream_pid'
assert_not_matches "$BOOTSTRAP" '^[[:space:]]*exec[[:space:]]+.*(docker-entrypoint|postgres|upstream)'

assert_literal "$STORAGE" 'configs:'
assert_count_at_least "$STORAGE" 'cert-watch\.sh' 2
assert_literal "$STORAGE" '/lego:ro'
assert_literal "$STORAGE" 'SSL_CERT_FILE=/ssl_certificates/fullchain.pem'
assert_literal "$STORAGE" 'SSL_KEY_FILE=/ssl_certificates/privkey.pem'

fixture_dir=$(mktemp -d)
cleanup() {
    rm -rf -- "$fixture_dir"
}
trap cleanup EXIT HUP INT TERM

source_dir="$fixture_dir/source"
target_dir="$fixture_dir/target"
target_empty="$fixture_dir/target-empty"
mkdir -m 700 "$source_dir" "$target_empty"
mkdir -m 755 "$target_dir"

cert_a="$fixture_dir/cert-a.pem"
key_a="$fixture_dir/key-a.pem"
cert_b="$fixture_dir/cert-b.pem"
key_b="$fixture_dir/key-b.pem"
cert_short="$fixture_dir/cert-short.pem"
key_short="$fixture_dir/key-short.pem"
openssl req -x509 -newkey rsa:2048 -nodes -days 2 \
    -subj '/CN=cert-watch-a' -keyout "$key_a" -out "$cert_a" >/dev/null 2>&1
openssl req -x509 -newkey rsa:2048 -nodes -days 2 \
    -subj '/CN=cert-watch-b' -keyout "$key_b" -out "$cert_b" >/dev/null 2>&1
openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
    -subj '/CN=cert-watch-short' -keyout "$key_short" -out "$cert_short" >/dev/null 2>&1
chmod 600 "$key_a" "$key_b" "$key_short"

source_cert="$source_dir/fullchain.pem"
source_key="$source_dir/privkey.pem"
reload_count="$fixture_dir/reload-count"
reload_hook="$fixture_dir/reload-hook.sh"
after_copy_hook="$fixture_dir/after-copy-hook.sh"
run_log="$fixture_dir/run.log"
owner="$(id -u):$(id -g)"
AFTER_COPY_HOOK_VALUE=
FAIL_FILE_VALUE=
MUTATION_CERT_VALUE=
MIN_VALIDITY_SECONDS_VALUE=0

cat > "$reload_hook" <<'HOOK'
#!/bin/sh
set -eu
count_file=${CERT_WATCH_TEST_RELOAD_COUNT:?}
printf '%s\n' reload >> "$count_file"
if [ -n "${CERT_WATCH_TEST_RELOAD_FAIL_FILE:-}" ] && [ -e "$CERT_WATCH_TEST_RELOAD_FAIL_FILE" ]; then
    exit 23
fi
HOOK
chmod 700 "$reload_hook"

cat > "$after_copy_hook" <<'HOOK'
#!/bin/sh
set -eu
cp "${CERT_WATCH_TEST_MUTATION_CERT:?}" "${CERT_WATCH_SOURCE_CERT:?}"
HOOK
chmod 700 "$after_copy_hook"

copy_pair() {
    cp "$1" "$source_cert"
    cp "$2" "$source_key"
    chmod 644 "$source_cert"
    chmod 600 "$source_key"
}

run_watcher() {
    if \
        CERT_WATCH_SOURCE_CERT="$source_cert" \
        CERT_WATCH_SOURCE_KEY="$source_key" \
        CERT_WATCH_TARGET_DIR="$target_dir" \
        CERT_WATCH_OWNER="$owner" \
        CERT_WATCH_MIN_VALIDITY_SECONDS="$MIN_VALIDITY_SECONDS_VALUE" \
        CERT_WATCH_TEST_MODE=1 \
        CERT_WATCH_RELOAD_HOOK="$reload_hook" \
        CERT_WATCH_AFTER_COPY_HOOK="$AFTER_COPY_HOOK_VALUE" \
        CERT_WATCH_ONCE=1 \
        CERT_WATCH_TEST_RELOAD_COUNT="$reload_count" \
        CERT_WATCH_TEST_RELOAD_FAIL_FILE="$FAIL_FILE_VALUE" \
        CERT_WATCH_TEST_MUTATION_CERT="$MUTATION_CERT_VALUE" \
        timeout 20s "$WATCHER" "$@" > "$run_log" 2>&1
    then
        LAST_STATUS=0
    else
        LAST_STATUS=$?
    fi
}

case_start \
    'the source contains a valid certificate/key pair and the target is empty' \
    'the watcher runs once with --no-reload' \
    'the pair is installed as cert 0644 and key 0600 without a reload'
rm -f "$target_dir/fullchain.pem" "$target_dir/privkey.pem" "$target_dir/.cert-watch.pending"
copy_pair "$cert_a" "$key_a"
: > "$reload_count"
AFTER_COPY_HOOK_VALUE=
FAIL_FILE_VALUE=
MUTATION_CERT_VALUE=
run_watcher --no-reload
assert_status_zero 'startup valid pair install'
assert_hash_equal "$cert_a" "$target_dir/fullchain.pem"
assert_hash_equal "$key_a" "$target_dir/privkey.pem"
assert_mode "$target_dir/fullchain.pem" 644
assert_mode "$target_dir/privkey.pem" 600
assert_owner "$target_dir/fullchain.pem" "$owner"
assert_mode "$target_dir" 700
assert_owner "$target_dir" "$owner"
assert_owner "$target_dir/privkey.pem" "$owner"
assert_reload_count 0
assert_no_pending
assert_target_clean

case_start \
    'the installed pair is unchanged' \
    'the watcher runs once without a reload override' \
    'the target is unchanged and no reload occurs'
: > "$reload_count"
run_watcher
assert_status_zero 'unchanged input'
assert_hash_equal "$cert_a" "$target_dir/fullchain.pem"
assert_hash_equal "$key_a" "$target_dir/privkey.pem"
assert_reload_count 0
assert_no_pending
assert_target_clean

case_start \
    'the source changes to a second valid pair' \
    'the watcher runs once' \
    'the new pair is installed and reload runs exactly once'
copy_pair "$cert_b" "$key_b"
: > "$reload_count"
run_watcher
assert_status_zero 'changed valid pair'
assert_hash_equal "$cert_b" "$target_dir/fullchain.pem"
assert_hash_equal "$key_b" "$target_dir/privkey.pem"
assert_reload_count 1
assert_no_pending
assert_target_clean

case_start \
    'the source certificate and key do not match' \
    'the watcher runs once' \
    'the last-good pair is preserved and no reload occurs'
cp "$cert_a" "$source_cert"
cp "$key_b" "$source_key"
: > "$reload_count"
run_watcher
assert_status_zero 'mismatched pair'
assert_hash_equal "$cert_b" "$target_dir/fullchain.pem"
assert_hash_equal "$key_b" "$target_dir/privkey.pem"
assert_reload_count 0
assert_no_pending
assert_target_clean

case_start \
    'the source key is missing while the last-good pair is installed' \
    'the watcher runs once' \
    'the last-good pair is preserved and no reload occurs'
copy_pair "$cert_b" "$key_b"
rm -f "$source_key"
: > "$reload_count"
run_watcher
assert_status_zero 'missing key'
assert_hash_equal "$cert_b" "$target_dir/fullchain.pem"
assert_hash_equal "$key_b" "$target_dir/privkey.pem"
assert_reload_count 0
assert_no_pending
assert_target_clean

case_start \
    'the source is invalid and the target has no installed pair' \
    'the watcher runs once' \
    'the watcher fails without creating an installed pair or reloading'
printf '%s\n' invalid > "$source_cert"
printf '%s\n' invalid > "$source_key"
target_dir="$target_empty"
: > "$reload_count"
run_watcher
[ "$LAST_STATUS" -ne 0 ] || fail 'invalid source with no installed pair unexpectedly succeeded'
assert_reload_count 0
if find "$target_empty" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    fail 'invalid source created files without an installed pair'
fi

target_dir="$fixture_dir/target"
copy_pair "$cert_b" "$key_b"

case_start \
    'the source is valid when copied but mutates before activation' \
    'the watcher runs once with an after-copy hook that changes the source certificate' \
    'the last-good pair is preserved and no reload occurs'
copy_pair "$cert_a" "$key_a"
AFTER_COPY_HOOK_VALUE="$after_copy_hook"
FAIL_FILE_VALUE=
MUTATION_CERT_VALUE="$cert_b"
: > "$reload_count"
run_watcher
assert_status_zero 'source mutation after copy'
assert_hash_equal "$cert_b" "$target_dir/fullchain.pem"
assert_hash_equal "$key_b" "$target_dir/privkey.pem"
assert_reload_count 0
assert_no_pending
assert_target_clean

case_start \
    'the source changes to a valid pair and the reload hook fails' \
    'the watcher runs once, then runs again unchanged after the hook is repaired' \
    'the first run leaves a pending marker and the second run retries once and removes it'
copy_pair "$cert_a" "$key_a"
AFTER_COPY_HOOK_VALUE=
FAIL_FILE_VALUE="$fixture_dir/reload-failure"
MUTATION_CERT_VALUE=
: > "$reload_count"
: > "$FAIL_FILE_VALUE"
run_watcher
assert_hash_equal "$cert_a" "$target_dir/fullchain.pem"
assert_hash_equal "$key_a" "$target_dir/privkey.pem"
assert_reload_count 1
[ -f "$target_dir/.cert-watch.pending" ] || fail 'reload failure did not leave a pending marker'
assert_target_clean
rm -f "$source_key"
rm -f "$FAIL_FILE_VALUE"
run_watcher
assert_status_zero 'pending reload retry'
assert_hash_equal "$cert_a" "$target_dir/fullchain.pem"
assert_hash_equal "$key_a" "$target_dir/privkey.pem"
assert_reload_count 2
assert_no_pending
assert_target_clean

case_start \
    'the fullchain appends a one-day certificate after a matching two-day leaf' \
    'the watcher requires 129600 seconds of validity for every certificate' \
    'the last-good pair is preserved and no reload occurs'
copy_pair "$cert_a" "$key_a"
cat "$cert_a" "$cert_short" > "$source_cert"
cp "$key_a" "$source_key"
chmod 644 "$source_cert"
chmod 600 "$source_key"
MIN_VALIDITY_SECONDS_VALUE=129600
: > "$reload_count"
run_watcher
assert_status_zero 'fullchain member validity'
assert_hash_equal "$cert_a" "$target_dir/fullchain.pem"
assert_hash_equal "$key_a" "$target_dir/privkey.pem"
assert_reload_count 0
assert_no_pending
assert_target_clean
MIN_VALIDITY_SECONDS_VALUE=0

printf 'PASS: cert-watch contract fixtures and static source checks\n'
