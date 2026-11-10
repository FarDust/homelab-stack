# A warning printed by every credentialless client says nothing about the holder

Some tools print a storage warning such as "primary unavailable (this process has no connection string)" whenever they run without the database credential. That text comes from every process that lacks the credential, including short-lived command-line helpers designed to write to a local mirror and let the credential holder reconcile.

## Rule

Before concluding that a credential or the database is missing, read the credential holder's own log for its storage line (source selected, primary verified, reconcile committed). The holder's log decides; the helper's warning does not.

## Check

1. Find the long-running process that owns the credential and read its log for lines such as `primary and mirror verified` or `reconcile committed`.
2. Inspect the mirror for pending rows; a pending count of zero means the holder caught up.
3. Only then investigate connectivity.

## Related

- [Client pools versus the server idle-session timeout](postgres-client-pool-vs-server-idle-session-timeout.md): the real fault that hid behind this warning.
