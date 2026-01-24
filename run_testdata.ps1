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

function Test-PortOpen($port, $maxRetries = 10, $delayMs = 500) {
    for ($i = 0; $i -lt $maxRetries; $i++) {
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if ($conn) { return $true }
        Start-Sleep -Milliseconds $delayMs
    }
    return $false
}

try {
    $backend = Start-Process -FilePath "cmd" -ArgumentList "/c cd /d `"$scriptDir\backend`" && call venv\Scripts\activate.bat && python main.py --mode testdata" -PassThru -NoNewWindow

    Write-Host "Waiting for backend to start..." -NoNewline
    if (-not (Test-PortOpen 5000)) {
        Write-Host " FAILED" -ForegroundColor Red
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Red
        Write-Host "  Backend failed to start!" -ForegroundColor Red
        Write-Host "  Check for Python errors above." -ForegroundColor Red
        Write-Host "========================================" -ForegroundColor Red
        Write-Host ""
        Write-Host "Press any key to exit..."
        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
        exit 1
    }
    Write-Host " OK" -ForegroundColor Green

    Start-Process "http://localhost:5173"
    $frontend = Start-Process -FilePath "cmd" -ArgumentList "/c cd /d `"$scriptDir\langgraph-studio`" && npm run dev" -PassThru -NoNewWindow -Wait
} finally {
    Write-Host "`nStopping servers..."
    if ($backend -and !$backend.HasExited) {
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
        $proc = Get-NetTCPConnection -LocalPort 5000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess
        if ($proc) { Stop-Process -Id $proc -Force -ErrorAction SilentlyContinue }
    }
    if ($frontend -and !$frontend.HasExited) {
        Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Done."
}
