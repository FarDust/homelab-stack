# LiteLLM config version and rollback reference

The gateway reads its configuration from a Swarm config whose name carries `CONFIG_VERSION`. Swarm configs are immutable, so a change is a new version and a redeploy.

## Procedure

1. Bump `CONFIG_VERSION` in the same commit as the config change.
2. Record the previous version as the rollback reference before deploying.
3. Deploy the single stack and wait for the replicas to converge; a restart of the gateway must leave the service intact (replicas running, healthcheck passing).
4. Verify behaviour through the public alias, not only the service state.
5. To roll back, set `CONFIG_VERSION` to the recorded reference and redeploy; keep the old config object until the new version is proven.

## Notes

- Environment variables are not interpolated inside Swarm config contents; reference them as `os.environ/NAME` in the gateway config.
- Report the deployed version, the rollback reference and the verification result together.

## Related

- [LiteLLM versioned upgrade ADR](../adr/litellm_versioned_upgrade_adr.md)
- [Local text-only fallback design](litellm-local-text-only-fallback-design.md)

Entities: [[LiteLLM]], [[Docker Swarm Config Versioning]]
