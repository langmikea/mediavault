# v0.6 Item 3 — orchestrate the schema migration on Mike's machine.
#
# 1. Stops any running imgserver listening on 51822.
# 2. Runs v06_phase3_migration.py against C:\AI\Platform\MediaVault\core\mediavault.sqlite.
# 3. Aborts (does NOT relaunch the server) if the migration exits non-zero,
#    so the bad state is obvious.
# 4. Relaunches imgserver in a *visible* console window and waits for /ping.
#
# Run from anywhere:
#     pwsh -ExecutionPolicy Bypass -File C:\AI\Platform\MediaVault\_cowork\v06_phase3_run.ps1

$ErrorActionPreference = "Stop"

$root      = "C:\AI\Platform\MediaVault"
$python    = "python"
$server    = Join-Path $root "core\imgserver.py"
$migration = Join-Path $root "_cowork\v06_phase3_migration.py"
$port      = 51822

Write-Host "=== STEP 1: stop any imgserver on :$port ==="
$listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($listeners) {
    $pids = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($targetPid in $pids) {
        Write-Host "  killing PID $targetPid"
        Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
} else {
    Write-Host "  no listener on :$port"
}

Write-Host ""
Write-Host "=== STEP 2: run migration ==="
Push-Location $root
try {
    & $python $migration
    $rc = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($rc -ne 0) {
    Write-Host ""
    Write-Host "MIGRATION FAILED (exit $rc). Server NOT restarted." -ForegroundColor Red
    Write-Host "Backup file is in $root\core\ — restore it if needed:"
    Write-Host "  Get-ChildItem '$root\core\mediavault.sqlite.bak_pre_v06_*' | Sort-Object LastWriteTime -Desc | Select-Object -First 1"
    exit $rc
}

Write-Host ""
Write-Host "=== STEP 3: relaunch imgserver (visible window) ==="
$args = @($server)
Start-Process -FilePath $python `
    -ArgumentList $args `
    -WorkingDirectory $root `
    -WindowStyle Normal

Write-Host "  waiting for /ping ..."
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $resp = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/ping" -TimeoutSec 2
        if ($resp.StatusCode -eq 200) { $ok = $true; break }
    } catch { }
}
if ($ok) {
    Write-Host "  /ping OK ✓" -ForegroundColor Green
} else {
    Write-Host "  /ping never responded — check the imgserver console window." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done. Next step: run the regression + smoke tests."
Write-Host "  python $root\_cowork\v06_tag_create_test.py"
Write-Host "  python $root\_cowork\v06_smoke_tag_create.py"
