# ADR: Preserve scheduled rotation alongside the rsyslog size limit

Date: 2026-11-13

Status: reviewed source candidate; live activation pending preservation and side-effect review.

## Context

A worker root filesystem remained 99% full while its Docker data directory was
on a separate filesystem. Rootful Docker pruning cannot recover that root
filesystem. A separate rootless development engine and retained platform data
also occupy root; the complete dominant consumer remains unproven.

One independently verified contributor was 10.37 GiB in `/var/log`. The local
rsyslog conffile used `daily` followed by `size 5G` for syslog, and `weekly`
followed by `size 5G` for secondary logs. A native logrotate debug run explicitly
reported that `size` overrides both schedules. It skipped a 2.8 GiB syslog and
1.5 GiB kernel log below the threshold even though their recorded rotations were
long overdue. Delayed compression left a 5,614,521,331-byte syslog archive
uncompressed until another rotation.

The daily logrotate service was successful. Its schedule was not the failure:
the later conffile directive selected size-only behavior. These measurements
prove a retention-policy defect and its contribution; they do not attribute the
entire root filesystem to logs.

## Decision

Track the reviewed conffile in
[`host-config/logrotate/rsyslog.conf`](../../host-config/logrotate/rsyslog.conf).
Change only the two `size 5G` directives to `maxsize 5G`, preserving the daily and
weekly schedules alongside the early size threshold. Keep the same log paths,
rotation counts, compression behavior and distribution postrotate helper.

Use the already installed logrotate implementation for scheduling, state,
compression and rotation. No custom pruner or timer is added. The native test
target was logrotate 3.21.0 with rsyslog 8.2312; this change adds no dependency.
The upstream contract explains the distinction between
[`size` and `maxsize`](https://github.com/logrotate/logrotate/blob/main/logrotate.8.in).

The established [`node-retention` tool](../../tools/node-retention/README.md)
owns the regression checks. Its existing CI explicitly selects Python 3.13,
its package-local pin is 3.13 and the package requires Python >=3.12.
The root composition environment and the independent nested cluster-utils
repository are not executed or modified by these tests.

## Alternatives

- Force rotation or delete/compress archives immediately: deferred because
  diagnostic preservation and recovery have not been verified.
- Remove the size limit: unnecessary; `maxsize` preserves the existing 5 GiB
  threshold and restores the intended time schedule.
- Lower the size threshold or change rotation counts: outside the proven
  two-directive defect and a separate retention decision.
- Extend the legacy Docker pruner or create a new cleanup daemon: does not
  repair the rsyslog schedule and would duplicate established retention tooling.

## Activation and rollback contract

This source candidate is not installed by a Swarm deployment, by `node-retention
apply`, or merely by merging it. The named integration owner coordinates the
host file through the canonical host-maintenance path once its target and
authorization are explicit. A host-config deployment command is not claimed to
exist in cluster-utils.

Before activation, inventory and preserve the complete affected log families
and the current conffile, state file, file metadata and the package-provided
conffile. Verify hashes and an independent recovery read. Re-run the native debug
plan against the current state and record every candidate for compression,
rename or deletion. Preserve records needed for crash/panic analysis before any
history can expire.

In the observed state, activating this candidate makes syslog, kern.log and
auth.log eligible at the next ordinary run. Counts are unchanged, but that run
would move the oldest retained archives beyond their counts and can delete
them. The observed oldest archives were 183,515, 142,197 and 3,113 bytes
respectively. Debug output is a simulation and does not perform those renames;
an "archive does not exist" message after a simulated rename does not prove no
archive would be deleted by a real run.

Configuration rollback before any rotation is restoring the verified conffile
preimage with its original ownership and mode, followed by another debug check.
The preserved regression fixture is
[`rsyslog-size-override.conf`](../../tools/node-retention/tests/fixtures/logrotate/rsyslog-size-override.conf);
deploy only a preimage whose hash matches the target's receipt. After a real
rotation, configuration rollback alone does not recover deleted history or undo
state/filename changes; use the independently verified preservation copy and
review recovery as a separate operation. No restart or forced rotation is part
of this change.

## Verification

[`test_logrotate_policy.py`](../../tools/node-retention/tests/test_logrotate_policy.py)
runs native logrotate in debug mode against synthetic log families and a copied
state file. It checks the legacy skip, restored due rotations, unchanged log and
state bytes, exact source scope and a native malformed-configuration rejection.
Missing native logrotate is an explicit failure. The target's privileged debug
checks also established that an ignored config can return exit zero; valid
receipts require successful parsing of both groups and no parser errors, beyond
checking the exit code alone.

The real target's copied, root-owned conffiles reproduced RED and GREEN with
`--debug`: both schedules were overridden in RED; GREEN restored daily/weekly
eligibility for all three observed files. Live conffile and state hashes were
unchanged. All four root-owned test fixtures were removed and their absence was
verified. Ordinary service activity continued, so no unchanged-size claim is
made for growing live logs.

Source tests, source integration, activation and recovered filesystem bytes are
separate receipts. Current recovered bytes remain zero; the full root capacity
incident remains open.
