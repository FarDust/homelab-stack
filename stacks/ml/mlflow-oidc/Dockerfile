# MLflow tracking server with the mlflow-oidc-auth plugin (Keycloak OIDC), see docs/adr/mlflow_oidc_auth_adr.md
# Build context: stacks/ml/mlflow-oidc/
FROM python:3.12-slim@sha256:a75662dfec8d90bd7161c91050be2e0a9b21d284f3b7a7253d5db25f7d583fb3 AS builder
WORKDIR /build
COPY requirements.lock /build/requirements.lock
RUN python -m pip install \
    --require-hashes \
    --only-binary :all: \
    --no-deps \
    --no-cache-dir \
    --target /opt/mlflow-oidc-deps \
    --requirement /build/requirements.lock

FROM python:3.12-slim@sha256:a75662dfec8d90bd7161c91050be2e0a9b21d284f3b7a7253d5db25f7d583fb3 AS runtime
ARG IMAGE_VERSION=0.0.0
LABEL org.opencontainers.image.title="mlflow-oidc" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      org.opencontainers.image.description="MLflow server plus mlflow-oidc-auth for Keycloak"
COPY --from=builder /opt/mlflow-oidc-deps /opt/mlflow-oidc-deps
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN groupadd --gid 65532 mlflow \
 && useradd --uid 65532 --gid 65532 --no-create-home --shell /usr/sbin/nologin mlflow \
 && mkdir -p /mlflow/artifacts /mlflow/state \
 && chown -R 65532:65532 /mlflow
ENV PYTHONPATH=/opt/mlflow-oidc-deps \
    PATH=/opt/mlflow-oidc-deps/bin:$PATH \
    PYTHONUNBUFFERED=1
WORKDIR /mlflow/state
USER 65532:65532
EXPOSE 5000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["server", "--app-name", "oidc-auth", "--host", "0.0.0.0", "--port", "5000"]
