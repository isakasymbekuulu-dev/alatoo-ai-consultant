<#
  Pull AlaToo server backups from the droplet to THIS Windows computer.
  Uses Windows' built-in ssh/scp (OpenSSH). Copies any server archives that
  aren't already present locally into <project>\backups\server\, and prunes to $Keep.

  Prereq: passwordless SSH to the droplet (run scripts\setup_pull_ssh.ps1 first).

  Install the DAILY auto-pull:
      powershell -ExecutionPolicy Bypass -File scripts\pull_server_backups.ps1 -Install
  Run a pull right now:
      powershell -ExecutionPolicy Bypass -File scripts\pull_server_backups.ps1
#>
param(
  [string]$DropletHost = "167.172.176.33",
  [string]$User        = "root",
  [string]$RemoteDir   = "/opt/alatoo-ai-consultant/backups/server",
  [int]$Keep           = 7,
  [int]$Port           = 22,
  [string]$At          = "10:00am",
  [switch]$Install
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root      = Split-Path -Parent $ScriptDir
$LocalDir  = Join-Path $Root "backups\server"

if ($Install) {
  $ps1 = $MyInvocation.MyCommand.Path
  $action   = New-ScheduledTaskAction -Execute "powershell.exe" `
              -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ps1`""
  $trigger  = New-ScheduledTaskTrigger -Daily -At $At
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable
  Register-ScheduledTask -TaskName "AlaToo pull server backups" -Action $action `
    -Trigger $trigger -Settings $settings -Description "Daily copy of droplet backups to this PC" -Force | Out-Null
  Write-Host "[install] Scheduled task 'AlaToo pull server backups' registered (daily at $At)."
  Write-Host "[install] Runs as your user when you're logged in; make sure 'ssh $User@$DropletHost echo OK' works without a prompt."
  return
}

New-Item -ItemType Directory -Force -Path $LocalDir | Out-Null
$sshTarget = "$User@$DropletHost"

Write-Host "[pull] listing remote archives on $sshTarget ..."
$remoteList = & ssh -p $Port -o BatchMode=yes -o StrictHostKeyChecking=accept-new $sshTarget `
              "ls -1t $RemoteDir/alatoo-server-*.tar.gz 2>/dev/null"
if ($LASTEXITCODE -ne 0 -or -not $remoteList) {
  Write-Error "Could not list remote backups. Check that 'ssh $sshTarget echo OK' works without a password."
  exit 1
}

$copied = 0
foreach ($remotePath in ($remoteList -split "`n" | Where-Object { $_ -ne "" })) {
  $name  = Split-Path $remotePath -Leaf
  $local = Join-Path $LocalDir $name
  if (Test-Path $local) { continue }
  Write-Host "[pull] downloading $name ..."
  & scp -p -P $Port -o BatchMode=yes -o StrictHostKeyChecking=accept-new "${sshTarget}:$remotePath" "$local"
  if ($LASTEXITCODE -eq 0) { $copied++ } else { Write-Warning "failed: $name" }
}
Write-Host "[pull] downloaded $copied new archive(s)."

# retention: keep newest $Keep locally
Get-ChildItem $LocalDir -Filter "alatoo-server-*.tar.gz" |
  Sort-Object LastWriteTime -Descending | Select-Object -Skip $Keep |
  ForEach-Object { Write-Host "[pull] pruning $($_.Name)"; Remove-Item $_.FullName -Force }

Write-Host "[pull] done. Local server backups in: $LocalDir"
Get-ChildItem $LocalDir -Filter "alatoo-server-*.tar.gz" | Sort-Object LastWriteTime -Descending |
  Select-Object Name, @{n='SizeMB';e={[math]::Round($_.Length/1MB)}}, LastWriteTime | Format-Table -AutoSize
