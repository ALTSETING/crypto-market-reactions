param(
    [int[]]$CrawlProcessIds = @(12216, 17228)
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$reports = Join-Path $projectRoot "reports"
$logs = Join-Path $projectRoot "logs"
$startedAt = Get-Date

Set-Location $projectRoot
while ($CrawlProcessIds | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }) {
    Start-Sleep -Seconds 30
}
$crawlFinishedAt = Get-Date

$reactionWatch = [System.Diagnostics.Stopwatch]::StartNew()
& $python -m scripts.calculate_reactions --start 2023-01-01 --end 2026-07-01 --symbols BTCUSDT ETHUSDT SOLUSDT --resume `
    1>> (Join-Path $logs "stage8_finalize.stdout.log") `
    2>> (Join-Path $logs "stage8_finalize.stderr.log")
if ($LASTEXITCODE -ne 0) { throw "calculate_reactions failed with exit code $LASTEXITCODE" }
$reactionWatch.Stop()

$auditWatch = [System.Diagnostics.Stopwatch]::StartNew()
& $python -m scripts.audit_dataset --start 2023-01-01 --end 2026-07-01 --symbols BTCUSDT ETHUSDT SOLUSDT `
    1>> (Join-Path $logs "stage8_finalize.stdout.log") `
    2>> (Join-Path $logs "stage8_finalize.stderr.log")
if ($LASTEXITCODE -ne 0) { throw "audit_dataset failed with exit code $LASTEXITCODE" }
$auditWatch.Stop()

& $python -m pytest -q `
    1>> (Join-Path $logs "stage8_finalize.stdout.log") `
    2>> (Join-Path $logs "stage8_finalize.stderr.log")
if ($LASTEXITCODE -ne 0) { throw "pytest failed with exit code $LASTEXITCODE" }

$finishedAt = Get-Date
@{
    watcher_started_at = $startedAt.ToUniversalTime().ToString("o")
    crawls_finished_at = $crawlFinishedAt.ToUniversalTime().ToString("o")
    reactions_seconds = $reactionWatch.Elapsed.TotalSeconds
    audit_seconds = $auditWatch.Elapsed.TotalSeconds
    finalized_at = $finishedAt.ToUniversalTime().ToString("o")
} | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $reports "stage8_process_times.json")
