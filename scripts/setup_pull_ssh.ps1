<#
  One-time setup of passwordless SSH from THIS Windows PC to the AlaToo droplet,
  so the daily auto-pull can run unattended.

  Run in PowerShell:
      powershell -ExecutionPolicy Bypass -File scripts\setup_pull_ssh.ps1

  It generates a dedicated key (no passphrase), adds an ssh config entry, then
  prints (a) your public key and (b) the exact one-liner to paste into the
  droplet's web console. Adding the key on the server is the ONE step you do
  yourself (it grants login access).
#>
param(
  [string]$DropletHost = "167.172.176.33",
  [string]$User        = "root",
  [string]$KeyName     = "alatoo_droplet"
)
$ErrorActionPreference = "Stop"

$sshDir = Join-Path $env:USERPROFILE ".ssh"
New-Item -ItemType Directory -Force -Path $sshDir | Out-Null
$key = Join-Path $sshDir $KeyName

if (-not (Test-Path $key)) {
  Write-Host "[setup] generating key $key (no passphrase)..."
  & ssh-keygen -t ed25519 -f $key -N '""' -C "alatoo-pull"
} else {
  Write-Host "[setup] key already exists: $key"
}

# ssh config Host block so 'ssh root@<host>' uses this key automatically
$cfg = Join-Path $sshDir "config"
if (-not (Test-Path $cfg)) { New-Item -ItemType File -Path $cfg | Out-Null }
if (-not (Select-String -Path $cfg -SimpleMatch "Host $DropletHost" -Quiet)) {
  $block = "`nHost $DropletHost`n    HostName $DropletHost`n    User $User`n    IdentityFile $key`n    IdentitiesOnly yes`n"
  Add-Content -Path $cfg -Value $block
  Write-Host "[setup] added Host block to $cfg"
} else {
  Write-Host "[setup] $cfg already has a 'Host $DropletHost' block (left as-is)"
}

$pub = (Get-Content "$key.pub").Trim()
Write-Host ""
Write-Host "==== STEP 1: your PUBLIC key (already saved locally) ===="
Write-Host $pub
Write-Host ""
Write-Host "==== STEP 2: paste THIS into the droplet web console, then Enter ===="
Write-Host "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '$pub' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo KEY_ADDED"
Write-Host ""
Write-Host "==== STEP 3: back here, test the connection ===="
Write-Host "ssh $User@$DropletHost echo OK"
Write-Host ""
Write-Host "If it prints OK, run:  powershell -ExecutionPolicy Bypass -File scripts\pull_server_backups.ps1 -Install"
