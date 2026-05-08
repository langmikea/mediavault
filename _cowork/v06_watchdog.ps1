# v0.6 — MediaVault watchdog (alert-only).
#
# Runs hidden. Pings http://127.0.0.1:51822/ping every $POLL_INTERVAL_SEC.
# After $FAILURES_BEFORE_ALERT consecutive failures it shows ONE Yes/No
# MessageBox: "Relaunch now?" — Yes kills any zombie listener and starts
# imgserver in a hidden window; No dismisses and the watchdog stays quiet
# until the server has been seen up again at least once (so a single outage
# never spams more than one popup).
#
# Stop the watchdog: kill the pwsh process from Task Manager (it has no
# console window — sort by Name).
#
# Start manually:
#   pwsh -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden `
#     -File C:\AI\Platform\MediaVault\_cowork\v06_watchdog.ps1
# or just double-click _cowork\v06_watchdog_start.cmd

$ErrorActionPreference = 'SilentlyContinue'

# --- config -----------------------------------------------------------------
$ROOT                   = 'C:\AI\Platform\MediaVault'
$PYTHON                 = 'python'
$SERVER                 = Join-Path $ROOT 'core\imgserver.py'
$PORT                   = 51822
$PING_URL               = "http://127.0.0.1:$PORT/ping"
$POLL_INTERVAL_SEC      = 30   # how often to ping when healthy
$FAILURES_BEFORE_ALERT  = 2    # debounce: 2 consecutive misses before alerting
$RELAUNCH_WAIT_SEC      = 30   # how long to wait for /ping after relaunch
$LOG_PATH               = Join-Path $ROOT '_cowork\v06_watchdog.log'

# --- helpers ----------------------------------------------------------------
$wsh = New-Object -ComObject WScript.Shell

function Write-Log($msg) {
    $line = '{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    try { Add-Content -Path $LOG_PATH -Value $line -ErrorAction SilentlyContinue } catch {}
}

function Test-Server {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri $PING_URL -TimeoutSec 5
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Stop-Listener {
    $cons = Get-NetTCPConnection -LocalPort $PORT -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $cons) {
        try {
            Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
            Write-Log "  killed PID $($c.OwningProcess) on :$PORT"
        } catch {}
    }
    Start-Sleep -Seconds 1
}

function Start-ServerHidden {
    Start-Process -FilePath $PYTHON `
        -ArgumentList @($SERVER) `
        -WorkingDirectory $ROOT `
        -WindowStyle Hidden
    Write-Log "  launched imgserver hidden"
}

# --- main loop --------------------------------------------------------------
Write-Log "watchdog start (poll=$POLL_INTERVAL_SEC s, debounce=$FAILURES_BEFORE_ALERT)"

$consecFailures = 0
$alertedThisOutage = $false   # suppress repeat popups within one outage

while ($true) {
    if (Test-Server) {
        if ($consecFailures -gt 0) {
            Write-Log "server back up after $consecFailures failed ping(s)"
        }
        $consecFailures = 0
        $alertedThisOutage = $false   # reset; next outage may alert again
    }
    else {
        $consecFailures++
        Write-Log "ping failed ($consecFailures consecutive)"

        if ($consecFailures -ge $FAILURES_BEFORE_ALERT -and -not $alertedThisOutage) {
            $alertedThisOutage = $true
            $msg = "MediaVault server is not responding on port $PORT.`n`nRelaunch now?"
            # 4 = Yes/No, 48 = Warning icon. Return: 6=Yes, 7=No.
            $rc = $wsh.Popup($msg, 0, 'MediaVault watchdog', 52)
            if ($rc -eq 6) {
                Write-Log "user chose RELAUNCH"
                Stop-Listener
                Start-ServerHidden
                $ok = $false
                for ($i = 0; $i -lt $RELAUNCH_WAIT_SEC; $i++) {
                    Start-Sleep -Seconds 1
                    if (Test-Server) { $ok = $true; break }
                }
                if ($ok) {
                    Write-Log "relaunch OK — server responding"
                    $consecFailures = 0
                    $alertedThisOutage = $false
                } else {
                    Write-Log "relaunch FAILED — server still not responding after $RELAUNCH_WAIT_SEC s"
                    [void]$wsh.Popup(
                        "Relaunch failed — server is still not responding.`n`nDouble-click your MediaVault shortcut to start it manually and check the resulting console window for errors.",
                        0, 'MediaVault watchdog', 16)
                }
            } else {
                Write-Log "user dismissed alert (No) — staying quiet for this outage"
            }
        }
    }
    Start-Sleep -Seconds $POLL_INTERVAL_SEC
}
