#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'Usage:\n'
  printf '  %s init --env-file PATH --value POSITIVE_INT\n' "${0##*/}"
  printf '  %s bump --env-file PATH\n' "${0##*/}"
  printf '  %s --help\n' "${0##*/}"
}

if (( $# == 1 )) && [[ "$1" == '--help' ]]; then
  usage
  exit 0
fi

operation="${1:-}"
case "${operation}" in
  init)
    if (( $# != 5 )) || [[ "$2" != '--env-file' || "$4" != '--value' ]]; then
      usage >&2
      exit 2
    fi
    env_file="$3"
    requested_version="$5"
    if [[ ! "${requested_version}" =~ ^[1-9][0-9]*$ ]]; then
      printf 'init value must be a positive integer\n' >&2
      exit 1
    fi
    ;;
  bump)
    if (( $# != 3 )) || [[ "$2" != '--env-file' ]]; then
      usage >&2
      exit 2
    fi
    env_file="$3"
    requested_version=''
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

if [[ -e "${env_file}" && ( ! -f "${env_file}" || -L "${env_file}" ) ]]; then
  printf '%s is not a regular file\n' "${env_file}" >&2
  exit 1
fi

if [[ "${operation}" == 'bump' && ! -f "${env_file}" ]]; then
  printf 'env file does not exist: %s\n' "${env_file}" >&2
  exit 1
fi

assignment_pattern='^[[:space:]]*(export[[:space:]]+)?GRAFANA_CONFIG_VERSION[[:space:]]*='
value_pattern='^([[:space:]]*(export[[:space:]]+)?GRAFANA_CONFIG_VERSION[[:space:]]*=[[:space:]]*)([1-9][0-9]*)([[:space:]]*(#.*)?)$'
assignment_count=0
current_version=''

if [[ -f "${env_file}" ]]; then
  while :; do
    line=''
    if IFS= read -r line; then
      has_newline=1
    else
      has_newline=0
      [[ -n "${line}" ]] || break
    fi

    if [[ "${line}" =~ ${assignment_pattern} ]]; then
      ((assignment_count += 1))
      if [[ "${line}" =~ ${value_pattern} ]]; then
        current_version="${BASH_REMATCH[3]}"
      else
        current_version='invalid'
      fi
    fi

    (( has_newline == 1 )) || break
  done < "${env_file}"
fi

if (( assignment_count > 1 )); then
  printf 'duplicate GRAFANA_CONFIG_VERSION assignments in %s\n' "${env_file}" >&2
  exit 1
fi

if [[ "${operation}" == 'init' ]]; then
  if (( assignment_count == 1 )); then
    printf 'GRAFANA_CONFIG_VERSION is already initialized in %s\n' "${env_file}" >&2
    exit 1
  fi
  next_version="${requested_version}"
else
  if (( assignment_count == 0 )); then
    printf 'GRAFANA_CONFIG_VERSION is not initialized in %s\n' "${env_file}" >&2
    exit 1
  fi
  if [[ "${current_version}" == 'invalid' ]]; then
    printf 'GRAFANA_CONFIG_VERSION must be a positive integer\n' >&2
    exit 1
  fi

  next_version=''
  carry=1
  for ((index = ${#current_version} - 1; index >= 0; index--)); do
    digit="${current_version:index:1}"
    if (( carry == 1 )); then
      if [[ "${digit}" == '9' ]]; then
        next_version="0${next_version}"
      else
        next_version="$((digit + 1))${next_version}"
        carry=0
      fi
    else
      next_version="${digit}${next_version}"
    fi
  done
  (( carry == 0 )) || next_version="1${next_version}"
fi

env_dir="$(dirname -- "${env_file}")"
if [[ ! -d "${env_dir}" ]]; then
  printf 'directory does not exist: %s\n' "${env_dir}" >&2
  exit 1
fi

tmp_file="$(mktemp -- "${env_file}.tmp.XXXXXX")"
cleanup() {
  rm -f -- "${tmp_file}"
}
trap cleanup EXIT INT TERM

if [[ "${operation}" == 'init' ]]; then
  if [[ -f "${env_file}" ]]; then
    cat -- "${env_file}" > "${tmp_file}"
    if [[ -s "${env_file}" ]]; then
      last_byte="$(tail -c 1 -- "${env_file}" | od -An -t x1 | tr -d '[:space:]')"
      [[ "${last_byte}" == '0a' ]] || printf '\n' >> "${tmp_file}"
    fi
  fi
  printf 'export GRAFANA_CONFIG_VERSION=%s\n' "${next_version}" >> "${tmp_file}"
else
  while :; do
    line=''
    if IFS= read -r line; then
      has_newline=1
    else
      has_newline=0
      [[ -n "${line}" ]] || break
    fi

    if [[ "${line}" =~ ${value_pattern} ]]; then
      line="${BASH_REMATCH[1]}${next_version}${BASH_REMATCH[4]}"
    fi
    printf '%s' "${line}" >> "${tmp_file}"
    (( has_newline == 0 )) || printf '\n' >> "${tmp_file}"
    (( has_newline == 1 )) || break
  done < "${env_file}"
fi

if [[ -f "${env_file}" ]]; then
  chmod --reference="${env_file}" "${tmp_file}"
fi
mv -f -- "${tmp_file}" "${env_file}"
trap - EXIT INT TERM

printf 'GRAFANA_CONFIG_VERSION=%s\n' "${next_version}"
