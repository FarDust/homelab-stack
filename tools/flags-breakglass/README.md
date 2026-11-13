# flags-breakglass

Switch a cluster feature flag when the Unleash admin panel is unusable. Decision and limits:
[`docs/adr/feature_flags_service_adr.md`](../../docs/adr/feature_flags_service_adr.md).

```sh
export FLAGS_BREAKGLASS_URL=https://flags.${LOCAL_DOMAIN}          # token route, works without oauth2-proxy
export FLAGS_BREAKGLASS_TOKEN_FILE=secrets/feature-flags/admin_token  # admin PAT (OpenBao secret/feature-flags/api)
export FLAGS_BREAKGLASS_DSN_FILE=secrets/feature-flags/db_url         # optional: database fallback
uv run --project tools/flags-breakglass flags-breakglass kill trail.recording
uv run --project tools/flags-breakglass flags-breakglass enable trail.recording
uv run --project tools/flags-breakglass flags-breakglass export --out /dev/shm/flags-snapshot.json
```

`kill` and `enable` use the admin API and read the state back. When no replica answers they update Unleash's
`feature_environments` table instead (needs the DSN and a route to PostgreSQL); that change takes effect when the service
starts again. Every command prints one JSON line on stdout and diagnostics on stderr, and exits non-zero on failure.
Tests: `uv run --project tools/flags-breakglass pytest`.
