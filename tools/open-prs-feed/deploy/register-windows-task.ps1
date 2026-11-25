# Thin launcher: registers a hidden 15-minute Task Scheduler entry that runs `open-prs-feed publish`.
# Usage: register-windows-task.ps1 -ProjectDir <deployed copy> -EnvFile <private env> [-Uv <uv.exe>]
# Runs as the current user, logged-on only, with no stored password. Uninstall:
#   Unregister-ScheduledTask -TaskName open-prs-feed -Confirm:$false
param(
    [Parameter(Mandatory)] [string] $ProjectDir,
    [Parameter(Mandatory)] [string] $EnvFile,
    [string] $Uv = (Get-Command uv).Source,
    [string] $TaskName = 'open-prs-feed'
)
$argLine = "--headless `"$Uv`" run --frozen --python 3.13 --project `"$ProjectDir`" open-prs-feed publish --env-file `"$EnvFile`""
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\conhost.exe" -Argument $argLine -WorkingDirectory $ProjectDir
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'Writes the open PR list node-retention reads; see docs/adr/open_prs_feed_adr.md' -Force | Out-Null
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
