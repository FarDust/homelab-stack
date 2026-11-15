# Bounded job reporting

Canonical source: the `node-retention-report` console entry point in
[`tools/node-retention`](../../tools/node-retention/README.md), the
[decision and evidence contract](../../docs/adr/ci_job_report_budget_adr.md),
[`gc-report.sh`](gc-report.sh), and [`gate-reporting.patch`](gate-reporting.patch).

The patch retires the historical shell report bodies, preserves destructive
retention/reaping and admission policy, records the original admission epoch and
duration, and loads a versioned reporting profile. It is not a Swarm deploy and
does not activate log rotation or prune data.

## Adoption gates

The named helper owner supplies the deployment mapping privately. Required inputs
are the verified installed helper digest/preimage, the immutable 0.4.0 wheel and
locked runtime, the configured existing ledger-publisher executable, the versioned
shim, and the existing shared ledger/jobs root. The example profile contains only
synthetic placeholders and is deliberately not an executable installation.

1. Complete independent review, locked package tests and native read-only
   synthetic before/after evidence. Verify the wheel-installed console/import
   contract and version, not an editable source import.
2. Stage the new runtime and shim in a fresh immutable version/digest directory;
   verify all hashes. Keep current runtimes, SDKs, ledger and active jobs intact.
3. Preserve the exact current helper and profile once. Re-read the current helper
   digest against the reviewed preimage; any drift is a conflict, not permission
   to overwrite another owner's work. Stage a copy, apply the patch with Git's
   `--unidiff-zero`, and require `bash -n` and an exact expected rendered digest.
4. Exercise the staged helper/profile with an isolated synthetic ledger and jobs
   root. Invoke only reporting, not admission, removal or a live cleanup path.
   Confirm original-deadline denial, readable partial/unknown outcomes and
   the one-report compatibility dispatch.
5. Atomically install the complete profile and then the complete helper (`.new`
   file, preserved mode/owner, single rename). Never rewrite an in-use script in
   place. The profile points to the immutable runtime and shim; source imports
   and runtime hashes are verified after installation.
6. Observe a bounded future job to its actual process exit. Record payload/END
   and wrapper completion separately, the report status, elapsed report time and
   exact installed hashes. A queued/running process or END row is not completion.

## Rollback and reconstruction

The owner atomically restores the verified original helper preimage and previous
profile, preserving their modes/owners and checking the original digest and syntax.
Keep both immutable runtimes until every process that captured either profile has
ended. No ledger row or historical evidence is rewritten. A rollback of this
read-only boundary does not undo or authorize any retention action.

The generic mechanism is public; deployment paths, host identifiers and installed
publisher mappings belong in private operator receipts. No new agent lock,
coordinator, service restart or host-policy exception is required.
