# ADR: Independent secret gates in Linux CI

Date: 2026-10-11. Status: implemented; hosted execution and independent approval pending.

## Context

The previous workflow skipped the API scanner. The approved replacement requires the
maintained quota guard and an independent local scanner, while preserving ordinary
repository hooks. It must not depend on a production-node build or change deployment.

## Decision

Use one GitHub-hosted Ubuntu 24.04 job with a five-minute timeout, full Git history,
Python 3.12, uv 0.12.5, pre-commit 4.5.1 and Gitleaks 8.30.1. Actions are SHA-pinned;
the Gitleaks release archive is checksum-pinned. Cache uv dependencies and hook environments.
Retain applicable non-scanner hooks and the eight quota-boundary regression tests.

Run `uv run --python 3.12 --script scripts/secret_scan_guard.py ci`, then run Gitleaks
as a separate required step. The local scanner runs even when the API step fails;
neither step uses continue-on-error. Only the already-approved independently confirmed
zero-quota condition is non-blocking. Missing authentication and other failures block.

Provision the repository secret `GITGUARDIAN_API_KEY` through approved credential custody
before expecting a hosted pass. Its value is exposed only to the API step, not other
steps or source files. Fork PRs do not receive repository secrets and remain explicitly
blocked at that gate; do not use pull_request_target to expose credentials to PR code.

## Budget and lint interpretations

Owner: FarDust. Planning assumption, not measured demand: 60 runs/month at three Linux
minutes each gives 180 minutes/month. At the dated USD 0.006/minute list-price catalog,
gross cost is USD 1.08/month. Standard public-repository runner treatment is a separate
discount; no correctness or availability decision depends on a free allowance.
The five-minute timeout is a bound, not proof of the target's achieved wall time.

Two generic ci-budget lint findings have explicit interpretations:

- `duplicate-trigger`: push is restricted to main; feature updates run through PRs.
  A merge's main-branch validation is distinct from its feature-head validation. Avoid
  opening a PR sourced from main, which would overlap those events.
- `long-lived-secret`: this is a GitGuardian API credential, not a cloud deployment
  credential. The documented ggshield integration requires an API key; cloud OIDC/WIF
  is not a substitute for this API. Keep cloud deployment identity outside this job.

## Alternatives and verification

Skipping scanners, allowing every exit 128, disabling findings, compiling Gitleaks on
the production node, and using a self-hosted runner for this public repository were
rejected. No new credential was provisioned by this change.

Validate with actionlint, focused Linux tests and the actual range-scanning commands.
Review the exact published head independently. When Actions cannot acquire a runner,
record the actual billing/outage annotation and apply the approved independent local
fallback; a job that executes and fails remains a real failure. Merge only after the
coordinator's explicit PASS. This ADR does not claim hosted CI success.

Reference: https://docs.gitguardian.com/ggshield-docs/integrations/cicd-integrations/github-actions
