# Capacity retry loops need caps and fail-closed state

Launching a scarce free-tier shape (for example an ARM shape) usually answers "out of host capacity". A rescue loop that retries forever hides a stuck state and can hammer the API; a loop that guesses after an ambiguous failure can create duplicate resources.

## Design rules

- Bound the loop twice: an absolute deadline and an attempt cap. Both persist across restarts; a backoff reset never resets them.
- Use a cyclic backoff (for example 1, 2, 4, 8 minutes plus jitter) that returns to the start after the longest step instead of settling at a fixed maximum. Handle explicit throttling (429) with a few short jittered retries, then pause for review.
- Classify outcomes: explicit capacity error means wait and retry; an empty or unclassified response (HTTP 500 without a body) is not capacity and pauses the loop.
- Fail closed. A launch checkpoint left in `launching` after a crash means the outcome is unknown: reconcile with a read-only inventory check before any new launch, never launch again blindly.
- Reuse existing resources: check for the protective backup and for any instance already created; never create a backup per attempt.
- Write phase receipts (timestamps, process id, mode, phase, exit status) without arguments or response bodies, so the interruption point can be found later.
- Run under a lock so two workers never overlap, and keep the resource envelope fixed.

## Pitfalls

- Parsing persisted timestamps with implicit date conversion can swap day and month under mixed locales; keep ISO timestamps as strings or parse with an explicit format.
- A retry cadence is an operator policy, not a provider guarantee.

## Related

- [Node loss with a retained boot volume](node-loss-with-retained-boot-volume.md)
