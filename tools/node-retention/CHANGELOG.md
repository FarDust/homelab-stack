# Changelog

## 0.5.1

- Configure the cached ephemeral environments of each uv cache (`environments-v2`) as cache roots in the node
  example: a uv cache written every hour never passed the 24 h gate as a whole, so on frost-fang 7 GB of idle
  environments stayed on a root filesystem at 94 percent while the guard reported nothing left to prune. Each
  environment idle 24 h is now a least-recently-used candidate when the floor or budget needs it; uv rebuilds it
  from `archive-v0` without a download.
- Count a cache unit nested in another unit once and never plan both: the nested environments go first and
  the cache holding the archive is skipped. Regression tests added.

## 0.5.0

- Collect idle tmpfs job trees of finished lanes: idle time (120 min) with no running or deferred job in the lane,
  a 24 h ceiling for any lane, and an 8 GiB cap that evicts the oldest idle trees first; trees in use are never
  candidates. New `shm-gc [--dry-run]` command; `guard` runs it on every tick; each removal writes a ledger note
  with the manifest.
- Skip malformed job-ledger rows older than 48 h (`ledger_malformed_tolerance_hours`) instead of failing every
  run: three legacy rows had stopped all retention for five days. Recent or undated malformed rows still fail
  closed.

## 0.4.0

- Add the typed, read-only `node-retention-report` CLI with indexed process and
  container observations, original-job deadline enforcement, bounded worker
  cleanup and explicit partial/unknown outcomes.
- Reuse the configured canonical ledger publisher; retain owner/age/live/dedup
  policy and keep deletion and admission behavior unchanged.
- Publish completed findings incrementally before further inventory reads;
  preserve structured names, complete process paths and measured tree identity.
- Add native/behavioral/failure/boundary regressions and source-aware uv cache keys.
