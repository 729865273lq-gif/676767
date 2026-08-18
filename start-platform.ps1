param([switch]$NoBrowser)
# Trade Axis one-click launcher: Docker data services -> backend API -> frontend -> browser.
# Idempotent: skips anything already running. Safe to run any time.

$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$docker = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
$logPath = Join-Path $repo 'launcher.log'

function Log([string]$message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $message"
    Add-Content -Path $logPath -Value $line -Encoding UTF8
}

function Fail([string]$message) {
    Log "FAIL: $message"
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        "Trade Axis 启动失败：`n`n$message`n`n详情见 $logPath",
        'Trade Axis', 'OK', 'Error') | Out-Null
    exit 1
}

function Test-Port([int]$port) {
    try {
        $conn = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
        return [bool]$conn
    } catch { return $false }
}

function Wait-Url([string]$url, [int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -eq 200) { return $true }
        } catch {}
        Start-Sleep -Seconds 2
    }
    return $false
}

Log "launcher started"

# --- 1. Docker engine ---
$engineOk = $false
try { & $docker info *> $null; if ($LASTEXITCODE -eq 0) { $engineOk = $true } } catch {}
if (-not $engineOk) {
    Log "starting Docker Desktop..."
    Start-Process 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
    $deadline = (Get-Date).AddSeconds(150)
    while ((Get-Date) -lt $deadline) {
        try { & $docker info *> $null; if ($LASTEXITCODE -eq 0) { $engineOk = $true; break } } catch {}
        Start-Sleep -Seconds 5
    }
}
if (-not $engineOk) { Fail 'Docker 引擎未能启动（等待 150 秒超时）' }
Log "docker engine ready"

# --- 2. Data services (Postgres / Redis / MinIO) ---
Set-Location $repo
& $docker compose -p foreigntrade up -d postgres redis minio *>> $logPath
if ($LASTEXITCODE -ne 0) { Fail 'Docker 数据服务启动失败（见 launcher.log）' }
Start-Sleep -Seconds 5
Log "data services up"

# --- 3. Backend API ---
if (-not (Test-Port 8000)) {
    Log "starting backend..."
    Start-Process -FilePath "$repo\backend\.venv\Scripts\python.exe" `
        -ArgumentList 'local_api_launcher.py' `
        -WorkingDirectory "$repo\backend" -WindowStyle Hidden | Out-Null
}
if (-not (Wait-Url 'http://127.0.0.1:8000/health' 60)) { Fail '后端 API 未能启动（8000 端口）' }
Log "backend ready"

# --- 4. Frontend (dev server; clears stale .next to dodge OneDrive corruption) ---
if (-not (Test-Port 3000)) {
    Log "cleaning .next and starting frontend..."
    Remove-Item "$repo\frontend\.next" -Recurse -Force -ErrorAction SilentlyContinue
    Start-Process -FilePath 'npm.cmd' -ArgumentList 'run', 'dev' `
        -WorkingDirectory "$repo\frontend" -WindowStyle Hidden | Out-Null
}
if (-not (Wait-Url 'http://127.0.0.1:3000/' 120)) { Fail '前端未能启动（3000 端口）' }
Log "frontend ready"

# --- 5. Open the browser ---
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:3000/' }
Log "all services ready: http://127.0.0.1:3000/"
