#!/bin/sh
set -eu

: "${MTU_TASKS_DNS:=tasks.main-mtu_mtu-probe}"
: "${MTU_PAYLOAD_SIZE:=1400}"
: "${MTU_INTERVAL:=30s}"
: "${MTU_TIMEOUT:=1s}"
: "${MTU_COUNT:=1}"
: "${MTU_SOURCE_NODE:=$(hostname)}"
: "${MTU_LOCAL_DOMAIN:=home}"

sed \
  -e "s|__MTU_TASKS_DNS__|${MTU_TASKS_DNS}|g" \
  -e "s|__MTU_PAYLOAD_SIZE__|${MTU_PAYLOAD_SIZE}|g" \
  -e "s|__MTU_INTERVAL__|${MTU_INTERVAL}|g" \
  -e "s|__MTU_TIMEOUT__|${MTU_TIMEOUT}|g" \
  -e "s|__MTU_COUNT__|${MTU_COUNT}|g" \
  -e "s|__MTU_SOURCE_NODE__|${MTU_SOURCE_NODE}|g" \
  -e "s|__MTU_LOCAL_DOMAIN__|${MTU_LOCAL_DOMAIN}|g" \
  /app/cfg/network_exporter.yml.tmpl > /app/cfg/network_exporter.yml

exec /app/network_exporter --config.file=/app/cfg/network_exporter.yml
