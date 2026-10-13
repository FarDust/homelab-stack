# Changelog

All notable changes to the `mlflow-oidc` image follow Semantic Versioning.

## [0.1.1] - 2026-10-13

- Pin SQLAlchemy to the 2.0 series (2.0.x): 2.1 resolves `postgresql://` URIs to psycopg v3, which is not installed, so the existing
  `MLFLOW_BACKEND_STORE_URI` form failed. Found by restoring a production dump into a throwaway PostgreSQL 17.

## [0.1.0] - 2026-10-13

- Initial image: MLflow 3.17.0 with mlflow-oidc-auth 9.0.4 and psycopg2-binary, installed from a hash-locked
  requirements file onto a digest-pinned python:3.12-slim base, running as UID 65532.
