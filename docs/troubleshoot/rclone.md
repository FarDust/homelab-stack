# Troubleshooting: rclone Docker Plugin Fails to Start After Hard Reboot

This guide explains how to recover the rclone Docker plugin when it fails to start after a hard reboot or power loss. The main issue is that the plugin's state file (`/var/lib/docker-plugins/rclone/cache/docker-plugin.state`) can become corrupted or contain stale mount entries, preventing rclone from starting.

---


## Problem

**After a hard reboot or power loss, the rclone Docker plugin may refuse to start.**

This is usually caused by a corrupted or inconsistent state file, often due to unclean shutdowns. The state file may contain stale or invalid mount entries, which block the plugin from enabling or operating correctly.


## Solution: Clean Up and Reset the State File


### 1. Inspect or Edit the State File (Optional)

If you want to review the current state or check for obvious corruption, you can open the file:

```sh
sudo vim /var/lib/docker-plugins/rclone/cache/docker-plugin.state
```


### 2. Remove All Mounts from the State File

To clear all mount entries (which are often the cause of startup failures after a crash), use `jq` to set the `mounts` array to empty for each entry:


```sh
sudo jq 'map(.mounts = [])' /var/lib/docker-plugins/rclone/cache/docker-plugin.state > /tmp/tmp.state \
  && sudo mv /tmp/tmp.state /var/lib/docker-plugins/rclone/cache/docker-plugin.state
```


### 3. Restart the rclone Plugin

After cleaning the state file, restart the rclone plugin to apply changes. This should now succeed even after a hard reboot:

```sh
sudo docker plugin disable rclone
sudo docker plugin enable rclone
```


### 4. Recovery Script (Recommended)

You can automate the cleanup and restart process with a simple script. This is especially useful after a power loss or unclean shutdown:


```bash
#!/bin/bash

STATE_FILE="/var/lib/docker-plugins/rclone/cache/docker-plugin.state"
TMP_FILE="/tmp/tmp.state"

echo "🧹 Cleaning up stale mounts in $STATE_FILE..."

echo "🔄 Restarting rclone plugin..."
sudo docker plugin disable rclone

sudo jq 'map(.mounts = [])' "$STATE_FILE" > "$TMP_FILE" && sudo mv "$TMP_FILE" "$STATE_FILE"

sudo docker plugin enable rclone

echo "✅ All set. Mounts cleaned, plugin live."
```


Save this script and run it with `sudo` to perform the cleanup and restart in one step. This is the fastest way to recover from a failed rclone plugin start after a hard reboot.

---


## Notes & Best Practices

- **Always back up the state file before making manual changes.**
- If you encounter errors enabling the plugin, double-check the state file for valid JSON (use `jq . <file>` to validate).
- These steps are safe for production but should be performed during a maintenance window if possible.
- If the state file is badly corrupted (not valid JSON), you may need to delete it and let rclone recreate it, but this will remove all remembered mounts.

---


**References:**
- [rclone Docker Plugin Documentation](https://rclone.org/docker/)
- [jq Manual](https://stedolan.github.io/jq/manual/)
