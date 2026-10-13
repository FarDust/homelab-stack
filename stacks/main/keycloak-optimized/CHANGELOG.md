# Changelog

All notable changes to the `keycloak-optimized` image follow Semantic Versioning. The image tag is the version in `VERSION`; the deployed reference is always a digest.

## [0.1.0] - 2026-10-13

- Initial image: Keycloak 26.4.7 (the version running in production on 2026-10-13, digest-pinned) with `kc.sh build` run at image build time for
  `db=postgres`, `health-enabled`, `metrics-enabled` and `vault=file`. Run it with `start --optimized`.
- No custom providers, no non-default features: the running server had none (`/opt/keycloak/providers` empty, `KC_FEATURES` unset).
- `HEALTHCHECK` probes `/health/ready` on the management port 9000.
- Creates an empty `/run/secrets` so `vault=file` starts even when no Swarm secret is mounted (found by the throwaway test: without it the server aborts with "The /run/secrets directory doesn't exist").
