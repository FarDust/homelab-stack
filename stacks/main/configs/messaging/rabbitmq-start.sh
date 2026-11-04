#!/bin/sh
set -eu
export RABBITMQ_DEFAULT_USER=platform
export RABBITMQ_DEFAULT_PASS="$(cat /run/secrets/rabbitmq_password)"
export RABBITMQ_DEFAULT_VHOST=platform
exec /usr/local/bin/docker-entrypoint.sh rabbitmq-server
