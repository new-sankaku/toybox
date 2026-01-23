$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Starting Backend + Frontend..."
Write-Host ""
Write-Host "  Backend: http://localhost:5000"
Write-Host "  Frontend: http://localhost:5173"
Write-Host ""
Write-Host "Press Ctrl+C to stop both servers."
Write-Host "========================================"

$backend = $null
$frontend = $null

try {
    $backend = Start-Process -FilePath "cmd" -ArgumentList "/c cd /d `"$scriptDir\backend`" && call venv\Scripts\activate.bat && python main.py --mode testdata" -PassThru -NoNewWindow
    Start-Sleep -Seconds 2
    Start-Process "http://localhost:5173"
    $frontend = Start-Process -FilePath "cmd" -ArgumentList "/c cd /d `"$scriptDir\langgraph-studio`" && npm run dev" -PassThru -NoNewWindow -Wait
} finally {
    Write-Host "`nStopping servers..."
    if ($backend -and !$backend.HasExited) {
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
        # Kill any remaining python processes on port 5000
        $proc = Get-NetTCPConnection -LocalPort 5000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess
        if ($proc) { Stop-Process -Id $proc -Force -ErrorAction SilentlyContinue }
    }
    if ($frontend -and !$frontend.HasExited) {
        Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Done."
}
