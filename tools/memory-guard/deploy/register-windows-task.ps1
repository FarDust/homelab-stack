# Thin launcher: registers a hidden, BelowNormal 5-minute Task Scheduler entry that runs `memory-guard check`.
# Usage: register-windows-task.ps1 -ProjectDir <deployed copy> -EnvFile <private env> [-Uv <uv.exe>]
# Runs as the current user, logged-on only, with no stored password. Uninstall:
#   Unregister-ScheduledTask -TaskName memory-guard -Confirm:$false
param(
    [Parameter(Mandatory)] [string] $ProjectDir,
    [Parameter(Mandatory)] [string] $EnvFile,
    [string] $Uv = (Get-Command uv).Source,
    [string] $TaskName = 'memory-guard'
)
$argLine = "--headless `"$Uv`" run --frozen --python 3.13 --project `"$ProjectDir`" memory-guard check --env-file `"$EnvFile`""
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\conhost.exe" -Argument $argLine -WorkingDirectory $ProjectDir
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$settings.Priority = 7  # BelowNormal
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'Alerts on low free virtual memory or RAM; read-only. See docs/adr/memory_guard_adr.md' -Force | Out-Null
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
