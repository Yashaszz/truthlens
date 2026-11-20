# TruthLens self-healing launcher.
# Starts the analysis server and a Cloudflare tunnel, keeps the PC awake while running, restarts anything that
# stops, and automatically points the permanent link (https://yashaszz.github.io/truthlens/) at the current tunnel.
# Run from the project folder:   powershell -ExecutionPolicy Bypass -File .\start-truthlens.ps1
# Stop with Ctrl+C.

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Py = Join-Path $Root "backend\.venv\Scripts\python.exe"
$Cf = Join-Path $env:LOCALAPPDATA "cloudflared.exe"
$Log = Join-Path $env:TEMP "truthlens-tunnel.log"
$Repo = "https://github.com/Yashaszz/truthlens.git"

$LogDir = Join-Path $env:LOCALAPPDATA "truthlens"
New-Item -ItemType Directory -Force $LogDir | Out-Null
$RunLog = Join-Path $LogDir "launcher.log"
function Say($m) {
  $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m
  Write-Host $line
  try { Add-Content -Path $RunLog -Value $line -Encoding UTF8 } catch {}
}

# Only one launcher at a time (auto-start at logon + a manual run must not fight each other).
$mutex = New-Object System.Threading.Mutex($false, "Local\TruthLensLauncher")
if (-not $mutex.WaitOne(0)) { Say "Another TruthLens launcher is already running - exiting."; exit 0 }

# Keep the computer awake while this script runs (no system settings are changed).
Add-Type -Namespace TL -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
[TL.Power]::SetThreadExecutionState(0x80000003) | Out-Null   # CONTINUOUS | SYSTEM_REQUIRED | AWAYMODE

if (-not (Test-Path $Cf)) {
  Say "Downloading cloudflared (official Cloudflare release)..."
  Invoke-WebRequest "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile $Cf
}

function Test-Server {
  try { (Invoke-WebRequest "http://127.0.0.1:8000/api/health" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 } catch { $false }
}

function Start-Server {
  Say "Starting TruthLens server..."
  Start-Process -FilePath $Py -ArgumentList "-m","uvicorn","app.main:app","--port","8000","--app-dir",(Join-Path $Root "backend") `
    -WorkingDirectory $Root -WindowStyle Hidden | Out-Null
  for ($i = 0; $i -lt 90; $i++) { if (Test-Server) { Say "Server is up."; return }; Start-Sleep 2 }
  Say "Server did not answer yet (models may still be loading)."
}

function Update-Link($url) {
  Say "Pointing https://yashaszz.github.io/truthlens/ at $url ..."
  $tmp = Join-Path $env:TEMP ("tl-pages-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
  git clone -q --depth 1 --branch gh-pages $Repo $tmp 2>$null
  if (-not (Test-Path "$tmp\index.html")) { Say "Could not fetch the permanent page (no internet?). Will retry."; return $false }
  $html = Get-Content "$tmp\index.html" -Raw
  $new = [regex]::Replace($html, 'const TARGET = "[^"]*"', ('const TARGET = "' + $url + '"'))
  if ($new -ne $html) {
    Set-Content "$tmp\index.html" $new -NoNewline -Encoding UTF8
    git -C $tmp add index.html
    git -C $tmp commit -q -m "Point permanent link at current engine tunnel"
    git -C $tmp push -q origin gh-pages 2>$null
    if ($LASTEXITCODE -ne 0) { Say "Push failed. Will retry."; Remove-Item $tmp -Recurse -Force; return $false }
    Say "Permanent link updated (live in about a minute)."
  } else { Say "Permanent link already points here." }
  Remove-Item $tmp -Recurse -Force
  return $true
}

function Start-Tunnel {
  if (Test-Path $Log) { Remove-Item $Log -Force }
  Say "Starting Cloudflare tunnel..."
  $p = Start-Process -FilePath $Cf -ArgumentList "tunnel","--url","http://localhost:8000","--logfile",$Log -WindowStyle Hidden -PassThru
  for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep 1
    if (Test-Path $Log) {
      $m = Select-String -Path $Log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1
      if ($m) { return @{ Proc = $p; Url = $m.Matches[0].Value } }
    }
  }
  Say "Tunnel did not report an address."
  return @{ Proc = $p; Url = $null }
}

# Clear out tunnels left over from an earlier run so only one public address exists.
Get-Process cloudflared -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $Cf } | ForEach-Object { try { $_.Kill() } catch {} }
if (-not (Test-Server)) { Start-Server } else { Say "Server already running." }
$t = Start-Tunnel
$linked = $false
$misses = 0
if ($t.Url) { Say "Tunnel: $($t.Url)"; $linked = Update-Link $t.Url }

Say "TruthLens is live at https://yashaszz.github.io/truthlens/  (keep this window open; Ctrl+C to stop)"
while ($true) {
  Start-Sleep 20
  if (-not (Test-Server)) { Say "Server stopped responding - restarting."; Start-Server }
  if ($t.Proc.HasExited -or -not $t.Url) {
    Say "Tunnel stopped - restarting."
    $t = Start-Tunnel
    $linked = $false
  }
  if ($t.Url -and -not $linked) { $linked = Update-Link $t.Url }
  # health check through the public tunnel; restart it if Cloudflare dropped it
  # (3 misses in a row, so a brief Wi-Fi blip doesn't churn the address)
  if ($t.Url) {
    try { Invoke-WebRequest ($t.Url + "/api/health") -UseBasicParsing -TimeoutSec 15 | Out-Null; $misses = 0 }
    catch {
      $misses++
      if ($misses -ge 3) { Say "Public tunnel not reachable - restarting it."; try { $t.Proc.Kill() } catch {}; $t.Url = $null; $misses = 0 }
    }
  }
}
