#!/bin/sh
set -eu
url=""
if [ -f /run/secrets/grafana_routine_n8n_webhook_url ]; then
  url="$(cat /run/secrets/grafana_routine_n8n_webhook_url)"
fi
mkdir -p /etc/grafana/provisioning/alerting
if [ -f /opt/grafana-contact-points.yml.tmpl ]; then
  sed "s|__GRAFANA_ROUTINE_N8N_WEBHOOK_URL__|${url}|g" /opt/grafana-contact-points.yml.tmpl > /etc/grafana/provisioning/alerting/contact_points.yml
fi
exec /run.sh
