<#
.SYNOPSIS
  Starts the whole project: Django and the website with its Cloudflare tunnel, each in its own window.

.EXAMPLE
  .\start.ps1            Start everything (anything already running is left alone).
  .\start.ps1 -Stop      Stop everything this script started, plus the tunnel.
  .\start.ps1 -DryRun    Show what would happen without starting anything.
#>
param(
  [switch]$Stop,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$root       = $PSScriptRoot
$djangoDir  = Join-Path $root "rafay\fountain-finder"
$nodeDir    = Join-Path $root "arthur\home"
$envFile    = Join-Path $root "arthur\.env"
$pidFile    = Join-Path $root ".launcher.pids"
$djangoPort = 8000
$nodePort   = 3000

function Say($text, $color = "Gray") { Write-Host $text -ForegroundColor $color }

function Get-ListenerPid($port) {
  $connection = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($connection) { return $connection.OwningProcess }
  return $null
}

# Kills a process and everything it started (for example node and its cloudflared).
function Stop-Tree($processId) {
  if ($processId) { & taskkill.exe /PID $processId /T /F 2>&1 | Out-Null }
}

# This project's own cloudflared (the one inside arthur\home\node_modules), if one is still around.
function Get-ProjectCloudflared {
  Get-Process cloudflared -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase) }
}

function Stop-Everything {
  if (Test-Path $pidFile) {
    foreach ($line in Get-Content $pidFile) { if ($line -match '^\d+$') { Stop-Tree ([int]$line) } }
    Remove-Item $pidFile -Force
  }
  foreach ($port in $djangoPort, $nodePort) { Stop-Tree (Get-ListenerPid $port) }
  foreach ($tunnel in @(Get-ProjectCloudflared)) { Stop-Tree $tunnel.Id }
}

function Wait-ForUrl($url, $seconds) {
  $deadline = (Get-Date).AddSeconds($seconds)
  while ((Get-Date) -lt $deadline) {
    try {
      Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3 -MaximumRedirection 0 -ErrorAction Stop | Out-Null
      return $true
    } catch {
      # A redirect or an error page still means the server is answering.
      if ($_.Exception.Response) { return $true }
      Start-Sleep -Milliseconds 700
    }
  }
  return $false
}

# Opens a new PowerShell window that stays open, runs the commands in it and returns the window's process.
function Start-Window($title, $dir, $commands) {
  $safeDir = $dir.Replace("'", "''")
  $script = "`$Host.UI.RawUI.WindowTitle = '$title'; Set-Location -LiteralPath '$safeDir'; $commands"
  $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
  return Start-Process powershell -ArgumentList "-NoExit", "-NoProfile", "-EncodedCommand", $encoded -PassThru
}

# ---------- Stop ----------

if ($Stop) {
  if ($DryRun) { Say "Dry run: would stop the Django and website windows and the tunnel." "Yellow"; exit 0 }
  Stop-Everything
  Say "Stopped Django, the website and the tunnel." "Green"
  exit 0
}

# ---------- Checks ----------

Say "Fountain Finder launcher" "Cyan"

$venvPython = Join-Path $root ".venv-backend\Scripts\python.exe"
if (Test-Path $venvPython) {
  $python = $venvPython
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
  $python = "python"
} else {
  Say "Python was not found. Install Python 3.12 or newer (tick 'Add python.exe to PATH'), then see README.md." "Red"
  exit 1
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
  Say "Node.js was not found. Install Node.js 20.12 or newer from https://nodejs.org, then see README.md." "Red"
  exit 1
}

& $python -c "import django, corsheaders" 2>$null
if ($LASTEXITCODE -ne 0) {
  Say "Django is not installed for $python." "Red"
  Say "Run the first-time setup in README.md (it creates .venv-backend and installs requirements.txt)." "Red"
  exit 1
}

foreach ($app in "home", "navigator", "uploader") {
  $appDir = Join-Path $root "arthur\$app"
  if (-not (Test-Path (Join-Path $appDir "node_modules"))) {
    if ($DryRun) { Say "Dry run: would run npm install in arthur\$app." "Yellow"; continue }
    Say "Installing packages for arthur\$app (first run only)..." "Yellow"
    & npm.cmd install --prefix $appDir
    if ($LASTEXITCODE -ne 0) { Say "npm install failed in arthur\$app." "Red"; exit 1 }
  }
}

if (-not (Test-Path $envFile)) {
  Say "Note: arthur\.env does not exist, so there is no Cloudflare token. You will get a temporary" "Yellow"
  Say "      random address instead of thirsttrips-ua.ca. Copy arthur\.env.example to arthur\.env to fix that." "Yellow"
}

# ---------- Start ----------

$djangoRunning = [bool](Get-ListenerPid $djangoPort)
$nodeRunning   = [bool](Get-ListenerPid $nodePort)
$started = @()

if ($djangoRunning) {
  Say "Django is already running on port $djangoPort, leaving it alone." "Yellow"
} elseif ($DryRun) {
  Say "Dry run: would open a window running 'manage.py migrate' and 'manage.py runserver' in $djangoDir" "Yellow"
} else {
  Say "Starting Django..." "Gray"
  $window = Start-Window "Fountain Finder - Django" $djangoDir "& '$python' manage.py migrate --noinput; & '$python' manage.py runserver"
  $started += $window.Id
}

if ($nodeRunning) {
  Say "The website is already running on port $nodePort, leaving it alone." "Yellow"
} else {
  # A tunnel left behind by a window that was closed would fight with the new one.
  foreach ($tunnel in @(Get-ProjectCloudflared)) {
    if ($DryRun) { Say "Dry run: would stop a leftover tunnel (process $($tunnel.Id))." "Yellow" }
    else { Say "Stopping a leftover tunnel from an earlier run..." "Yellow"; Stop-Tree $tunnel.Id }
  }
  if ($DryRun) {
    Say "Dry run: would open a window running 'npm run tunnel' in $nodeDir" "Yellow"
  } else {
    Say "Starting the website and tunnel..." "Gray"
    $window = Start-Window "Fountain Finder - Website and tunnel" $nodeDir "npm.cmd run tunnel"
    $started += $window.Id
  }
}

if ($DryRun) { exit 0 }

if ($started.Count -gt 0) {
  $existing = @()
  if (Test-Path $pidFile) { $existing = @(Get-Content $pidFile) }
  Set-Content -Path $pidFile -Value ($existing + $started)
}

# ---------- Wait until both answer ----------

$djangoOk = Wait-ForUrl "http://localhost:$djangoPort/login/" 60
$nodeOk   = Wait-ForUrl "http://localhost:$nodePort/" 60

Write-Host ""
if ($djangoOk) { Say "Django   ready   http://localhost:$djangoPort" "Green" } else { Say "Django   did not answer in time. Check its window for errors." "Red" }
if ($nodeOk)   { Say "Website  ready   http://localhost:$nodePort" "Green" } else { Say "Website  did not answer in time. Check its window for errors." "Red" }
Write-Host ""
Say "The public address appears in the website window ('Live at: ...') a few seconds after the tunnel connects."
Say "To stop everything:  .\start.ps1 -Stop   (or close the two windows)"
if (-not ($djangoOk -and $nodeOk)) { exit 1 }
