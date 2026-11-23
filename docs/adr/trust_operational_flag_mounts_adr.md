# Trust Agent operational flag credential mounts

## Context

A narrowly scoped operational flag capability needs an existing flag administration credential and an existing service identity credential. The source file locations are deployment-specific; their contents must stay out of configuration and logs.

## Decision

Mount each existing credential as a versioned Swarm secret and provide its in-container path to Trust Agent. The two required source-file variables identify protected files on the manager. The capability itself restricts callers and flag scope; mounting credentials expands what the Trust Agent process can read. A Trust-specific secret version preserves its existing references when the global configuration version changes. Retain prior source files and the previous image and secret references for rollback.

## Alternatives

Embedding values in environment variables or sending credentials in requests would expose them to additional surfaces. A new credential or broader grant is unnecessary for this operation. The preferred future custody carrier can replace these mounts after its own authorization and verification.

## Consequences

Deployments rendering this stack must supply both source-file variables. For rollback, render the saved pre-change service configuration with its recorded secret version, not the current global version. Confirm that the four existing secret references resolve to the exact pre-change objects before deployment. Remove only the two new mounts and environment entries, restore the previous image, and verify convergence and references. Disabling an owned flag is a separate action that preserves its rules. A collision or unconfirmed reference is an explicit stop.

## Verification

Check the environment contract and render without displaying values. Verify the two Swarm secret references, Trust Agent health and authorization through its consumer route. Treat unconfirmed side effects as unknown and preserve the prior release for rollback.
