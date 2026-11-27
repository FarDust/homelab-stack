# Thin launcher: registers a hidden, BelowNormal 1-minute Task Scheduler entry that runs `memory-guard publish-headroom`.
# Usage: register-headroom-task.ps1 -ProjectDir <deployed copy> -EnvFile <private env> [-Uv <uv.exe>]
# Publishes only while MEMORY_GUARD_HEADROOM_PUBLISH_ENABLED=true and the WSL distro already runs; never starts WSL.
# Runs as the current user, logged-on only, with no stored password. Uninstall:
#   Unregister-ScheduledTask -TaskName memory-guard-headroom -Confirm:$false

param(
    [Parameter(Mandatory)] [string] $ProjectDir,
    [Parameter(Mandatory)] [string] $EnvFile,
    [string] $Uv = (Get-Command uv).Source,
    [string] $TaskName = 'memory-guard-headroom'
)
$argLine = "--headless `"$Uv`" run --frozen --python 3.13 --project `"$ProjectDir`" memory-guard publish-headroom --env-file `"$EnvFile`""
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\conhost.exe" -Argument $argLine -WorkingDirectory $ProjectDir
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 1)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$settings.Priority = 7  # BelowNormal
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'Publishes Windows commit headroom as a node-exporter textfile in the running WSL guest (flag MEMORY_GUARD_HEADROOM_PUBLISH_ENABLED). See docs/adr/memory_guard_adr.md' -Force
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
