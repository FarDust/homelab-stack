# Rsyslog retention policy

`rsyslog.conf` is reviewed deployment source for `/etc/logrotate.d/rsyslog`.
It is not installed by a Swarm deployment or by `node-retention apply`.
The integration owner selects the target and records deployment separately.

The change preserves the daily syslog and weekly secondary-log schedules while
also allowing early rotation at 5 GiB. `size` overrides the schedule; `maxsize`
combines the size limit with it. Counts, log paths, delayed compression and the
existing distribution postrotate helper remain unchanged.

Read the [decision and activation contract](../../docs/adr/rsyslog_retention_schedule_adr.md)
before installation. The native regression tests live with the established
retention tool at `tools/node-retention/tests/test_logrotate_policy.py`; they use
synthetic logs and debug mode only.

Activation can immediately make old logs eligible for rotation, compression and
deletion under the existing counts. Preserve the entire affected log families,
their metadata, configuration and state before approving activation. Restoring a
configuration file cannot recover history that a rotation has already deleted.
