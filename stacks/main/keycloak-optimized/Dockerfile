# Keycloak with the build step done at image build time, so `start --optimized` skips the ~100 s re-augmentation on every restart.
# Decision record: docs/adr/keycloak_optimized_image_adr.md. Build context: stacks/main/keycloak-optimized/
# Keep KEYCLOAK_BASE in step with the Keycloak version the realm database was last migrated by; a bump is a MINOR image release.
ARG KEYCLOAK_BASE=quay.io/keycloak/keycloak:26.4.7@sha256:9409c59bdfb65dbffa20b11e6f18b8abb9281d480c7ca402f51ed3d5977e6007

FROM ${KEYCLOAK_BASE} AS builder
# Build-time options only. Everything else (db url, credentials, hostname, proxy headers, http) stays a runtime option.
# vault=file backs the Docker-secret references (${vault.*}) in realm settings such as SMTP; health and metrics serve the management port 9000.
ENV KC_DB=postgres \
    KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true \
    KC_VAULT=file
RUN /opt/keycloak/bin/kc.sh build

FROM ${KEYCLOAK_BASE} AS runtime
ARG IMAGE_VERSION=0.0.0
LABEL org.opencontainers.image.title="keycloak-optimized" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      org.opencontainers.image.description="Keycloak pre-built for PostgreSQL with health, metrics and file vault; run with start --optimized"
COPY --from=builder /opt/keycloak/ /opt/keycloak/
# vault=file refuses to start when its directory is missing; Swarm secret mounts replace this empty directory at runtime.
USER root
RUN mkdir -p /run/secrets && chmod 0755 /run/secrets
USER 1000
# The base image has no curl; probe the management port with bash. Ready means the realm database is reachable.
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=4 \
  CMD ["bash", "-c", "exec 3<>/dev/tcp/127.0.0.1/9000 && printf 'GET /health/ready HTTP/1.0\r\nHost: localhost\r\n\r\n' >&3 && head -n1 <&3 | grep -q ' 200 '"]
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
