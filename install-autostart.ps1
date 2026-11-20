# Makes TruthLens start by itself, hidden, every time you log in to Windows - and restarts it if it ever stops.
# Run once:   powershell -ExecutionPolicy Bypass -File .\install-autostart.ps1
# Undo:       powershell -ExecutionPolicy Bypass -File .\install-autostart.ps1 -Remove
param([switch]$Remove)
$Name = "TruthLens"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Launcher = Join-Path $Root "start-truthlens.ps1"

if ($Remove) {
  Stop-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
  Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host "Auto-start removed. (Running engine/tunnel windows are hidden; restart the PC or end python/cloudflared in Task Manager to stop them.)"
  exit 0
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Launcher`"" -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName $Name
Write-Host ""
Write-Host "Done. TruthLens now runs hidden in the background and starts automatically whenever you log in."
Write-Host "Live link: https://yashaszz.github.io/truthlens/   (give it ~2 minutes to come up)"
Write-Host "Log: $env:LOCALAPPDATA\truthlens\launcher.log"
