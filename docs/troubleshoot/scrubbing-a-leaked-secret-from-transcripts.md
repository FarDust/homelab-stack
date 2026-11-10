# Scrubbing a leaked secret from transcripts

When a credential reached a terminal or an agent transcript (for example from [`docker stack config`](docker-stack-config-prints-resolved-secrets.md)):

1. Identify the exact sinks: session transcripts, subagent transcripts, task output files, shell history, logs, and the working tree with its recent history.
2. Search for every encoded form (raw, URL-encoded, base64, JSON-escaped) with a tested helper, and mask matches in place so line counts and JSON validity are preserved.
3. Verify zero remaining occurrences after the scrub, and note any partial prefix fragments left deliberately.
4. Confirm the value is absent from the repository, its history and service logs.
5. Decide on rotation from evidence: a leak that stayed on the operator's own machine is not by itself a confirmed compromise, and a rotation needs a stability and custody plan. Record the decision and its reason.
6. Add a prevention guard (a masking wrapper or an agent-instruction rule) so the same command is not run unfiltered again.

Keep the value, its hash and its last characters out of notes and tickets; record the sink locations and the guard instead.
