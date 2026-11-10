# Reversible live network changes

Firewall, NAT and routing edits on a live node can cut the access you need to undo them. Arm the undo before the change, and let the change disarm it only after verification.

## Pattern

1. Snapshot the current state (`iptables-save`, `ip rule`, `ip route`) to a root-only file.
2. Arm a rollback with a named transient timer: `systemd-run --unit=rollback-<change> --on-active=<n>m <rollback script>`. The script removes only what the change added. Transient timers do not survive a reboot, so this guards against a lost session, not against a reboot.
3. Apply the change on one canary scope (one port, one rule).
4. Verify from the affected side (the network namespace that had the fault) and compare the unchanged tables with the snapshot.
5. Disarm the timer (`systemctl stop rollback-<change>.timer`) after the verification passes; extend the scope and repeat.
6. Persist the change through a reviewed unit only after the canary holds.

## Notes

- The rollback must also stop any reconcile timer that would reapply the change; otherwise the rollback is undone.
- Use bounded timer lengths that outlast the verification and not much more.
- Record the snapshot location and the rollback command in the change record.

## Related

- [gwbridge ingress DNAT remediation](gwbridge-ingress-dnat-remediation.md): a change rolled out with this pattern.
