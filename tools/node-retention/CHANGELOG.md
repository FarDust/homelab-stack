# Changelog

## 0.4.0

- Add the typed, read-only `node-retention-report` CLI with indexed process and
  container observations, original-job deadline enforcement, bounded worker
  cleanup and explicit partial/unknown outcomes.
- Reuse the configured canonical ledger publisher; retain owner/age/live/dedup
  policy and keep deletion and admission behavior unchanged.
- Publish completed findings incrementally before further inventory reads;
  preserve structured names, complete process paths and measured tree identity.
- Add native/behavioral/failure/boundary regressions and source-aware uv cache keys.
