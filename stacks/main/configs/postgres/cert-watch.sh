#!/bin/sh
set -eu

source_cert=${CERT_WATCH_SOURCE_CERT:-/lego/fullchain.pem}
source_key=${CERT_WATCH_SOURCE_KEY:-/lego/privkey.pem}
target_dir=${CERT_WATCH_TARGET_DIR:-/ssl_certificates}
owner=${CERT_WATCH_OWNER:-postgres:postgres}
min_validity=${CERT_WATCH_MIN_VALIDITY_SECONDS:-86400}
reload_hook=${CERT_WATCH_RELOAD_HOOK:-}
after_copy_hook=${CERT_WATCH_AFTER_COPY_HOOK:-}
test_mode=${CERT_WATCH_TEST_MODE:-}
interval=${CERT_WATCH_INTERVAL_SECONDS:-60}
pgdata=${PGDATA:-/var/lib/postgresql/17/main}
pg_ctl=/usr/lib/postgresql/17/bin/pg_ctl
reload_enabled=1
watch_mode=0
stage=
cert_tmp=
key_tmp=
pending_tmp=
last_source_warning=
last_reload_warning=

cleanup_paths() {
    test -z "$stage" || rm -rf "$stage" || :
    test -z "$cert_tmp" || rm -f "$cert_tmp" || :
    test -z "$key_tmp" || rm -f "$key_tmp" || :
    test -z "$pending_tmp" || rm -f "$pending_tmp" || :
    stage=
    cert_tmp=
    key_tmp=
    pending_tmp=
}

trap cleanup_paths 0
trap 'exit 130' HUP INT TERM

is_decimal() {
    case $1 in
        ''|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

warn_source_once() {
    if [ "$watch_mode" -eq 1 ] && [ -z "$last_source_warning" ]; then
        printf '%s\n' 'certificate source rejected' >&2
        last_source_warning=1
    fi
}

warn_reload_once() {
    if [ "$watch_mode" -eq 1 ] && [ -z "$last_reload_warning" ]; then
        printf '%s\n' 'certificate reload failed' >&2
        last_reload_warning=1
    fi
}

validate_fullchain() {
    cert_file=$1
    chain_dir=$2
    mkdir "$chain_dir" || return 1
    openssl crl2pkcs7 -nocrl -certfile "$cert_file" -out "$chain_dir/chain.p7" >/dev/null 2>&1 || return 1
    openssl pkcs7 -in "$chain_dir/chain.p7" -noout >/dev/null 2>&1 || return 1
    awk -v output_dir="$chain_dir" '
        /^-----BEGIN CERTIFICATE-----$/ {
            if (inside) exit 1
            count++
            file = output_dir "/certificate-" count ".pem"
            inside = 1
        }
        inside { print > file }
        /^-----END CERTIFICATE-----$/ {
            close(file)
            inside = 0
        }
        END {
            if (inside || count == 0) exit 1
        }
    ' "$cert_file" || return 1
    for chain_cert in "$chain_dir"/*.pem; do
        openssl x509 -in "$chain_cert" -noout >/dev/null 2>&1 || return 1
        openssl x509 -in "$chain_cert" -checkend "$min_validity" -noout >/dev/null 2>&1 || return 1
    done
}

validate_pair() {
    cert_file=$1
    key_file=$2
    work_dir=$3
    test -r "$cert_file" && test -s "$cert_file" || return 1
    test -r "$key_file" && test -s "$key_file" || return 1
    openssl x509 -in "$cert_file" -noout >/dev/null 2>&1 || return 1
    validate_fullchain "$cert_file" "$work_dir/chain" || return 1
    openssl pkey -in "$key_file" -passin pass: -noout >/dev/null 2>&1 || return 1
    openssl x509 -in "$cert_file" -pubkey -noout > "$work_dir/cert-public.pem" 2>/dev/null || return 1
    openssl pkey -in "$key_file" -pubout > "$work_dir/key-public.pem" 2>/dev/null || return 1
    cmp -s "$work_dir/cert-public.pem" "$work_dir/key-public.pem"
}

source_rejected() {
    installed_valid=$1
    cleanup_paths
    warn_source_once
    if [ "$installed_valid" -eq 1 ]; then
        return 0
    fi
    return 1
}

install_staged_pair() {
    cert_tmp=$(mktemp "$target_dir/.cert-watch.cert.XXXXXX") || return 1
    key_tmp=$(mktemp "$target_dir/.cert-watch.key.XXXXXX") || return 1
    cp "$stage/fullchain.pem" "$cert_tmp" || return 1
    cp "$stage/privkey.pem" "$key_tmp" || return 1
    chown "$owner" "$cert_tmp" "$key_tmp" || return 1
    chmod 0644 "$cert_tmp" || return 1
    chmod 0600 "$key_tmp" || return 1
    mv -f "$cert_tmp" "$target_dir/fullchain.pem" || return 1
    cert_tmp=
    mv -f "$key_tmp" "$target_dir/privkey.pem" || return 1
    key_tmp=
}

create_pending() {
    pending_tmp=$(mktemp "$target_dir/.cert-watch.pending.XXXXXX") || return 1
    : > "$pending_tmp"
    mv -f "$pending_tmp" "$target_dir/.cert-watch.pending" || return 1
    pending_tmp=
}

reload_postgres() {
    if [ -n "$reload_hook" ]; then
        "$reload_hook"
    else
        gosu postgres "$pg_ctl" -D "$pgdata" reload -s
    fi
}

retry_pending_reload() {
    if reload_postgres; then
        rm -f "$target_dir/.cert-watch.pending"
        last_reload_warning=
        return 0
    fi
    warn_reload_once
    return 1
}

sync_once() {
    final_cert=$target_dir/fullchain.pem
    final_key=$target_dir/privkey.pem
    pending=$target_dir/.cert-watch.pending
    installed_valid=0
    changed=0

    test ! -L "$target_dir" || return 1
    mkdir -p "$target_dir" || return 1
    chown "$owner" "$target_dir" || return 1
    chmod 0700 "$target_dir" || return 1
    stage=$(mktemp -d "$target_dir/.cert-watch.stage.XXXXXX") || return 1
    chmod 0700 "$stage" || return 1
    if test ! -L "$final_cert" && test ! -L "$final_key" && mkdir "$stage/installed-check" && validate_pair "$final_cert" "$final_key" "$stage/installed-check"; then
        installed_valid=1
    fi
    if [ "$reload_enabled" -eq 1 ] && [ "$installed_valid" -eq 1 ] && [ -e "$pending" ]; then
        if retry_pending_reload; then
            cleanup_paths
            return 0
        fi
        cleanup_paths
        return 1
    fi

    if ! test -r "$source_cert" || ! test -s "$source_cert" || ! test -r "$source_key" || ! test -s "$source_key"; then
        source_rejected "$installed_valid"
        return $?
    fi
    if ! sha256sum "$source_cert" > "$stage/source-cert.before" 2>/dev/null || ! sha256sum "$source_key" > "$stage/source-key.before" 2>/dev/null; then
        source_rejected "$installed_valid"
        return $?
    fi
    if ! cp "$source_cert" "$stage/fullchain.pem" || ! cp "$source_key" "$stage/privkey.pem"; then
        source_rejected "$installed_valid"
        return $?
    fi
    if [ -n "$after_copy_hook" ] && ! "$after_copy_hook"; then
        source_rejected "$installed_valid"
        return $?
    fi
    if ! sha256sum "$source_cert" > "$stage/source-cert.after" 2>/dev/null || ! sha256sum "$source_key" > "$stage/source-key.after" 2>/dev/null || ! cmp -s "$stage/source-cert.before" "$stage/source-cert.after" || ! cmp -s "$stage/source-key.before" "$stage/source-key.after"; then
        source_rejected "$installed_valid"
        return $?
    fi
    if ! validate_pair "$stage/fullchain.pem" "$stage/privkey.pem" "$stage"; then
        source_rejected "$installed_valid"
        return $?
    fi
    last_source_warning=
    chown "$owner" "$stage/fullchain.pem" "$stage/privkey.pem" || return 1
    chmod 0644 "$stage/fullchain.pem" || return 1
    chmod 0600 "$stage/privkey.pem" || return 1
    if ! cmp -s "$stage/fullchain.pem" "$final_cert" || ! cmp -s "$stage/privkey.pem" "$final_key"; then
        changed=1
        install_staged_pair || return 1
        if [ "$watch_mode" -eq 1 ]; then
            printf '%s\n' 'certificate pair activated' >&2
        fi
    fi
    if [ "$reload_enabled" -eq 0 ]; then
        rm -f "$pending"
        cleanup_paths
        return 0
    fi
    if [ "$changed" -eq 1 ]; then
        create_pending || return 1
    fi
    if [ -e "$pending" ]; then
        if retry_pending_reload; then
            cleanup_paths
            return 0
        fi
        cleanup_paths
        return 1
    fi
    cleanup_paths
    return 0
}

if { [ -n "$reload_hook" ] || [ -n "$after_copy_hook" ]; } && [ "$test_mode" != 1 ]; then
    exit 64
fi
for argument in "$@"; do
    case $argument in
        --no-reload) reload_enabled=0 ;;
        --watch) watch_mode=1 ;;
        *) exit 64 ;;
    esac
done
is_decimal "$min_validity" || exit 64
is_decimal "$interval" || exit 64
if [ "$watch_mode" -eq 1 ] && [ "$interval" -lt 10 ]; then
    interval=10
fi
if [ "${CERT_WATCH_ONCE:-}" = 1 ]; then
    watch_mode=0
fi
if [ "$watch_mode" -eq 0 ]; then
    sync_once
    exit $?
fi
while :; do
    if ! sync_once; then
        :
    fi
    sleep "$interval"
done
