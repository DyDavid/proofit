# Starts both local dev servers on Windows PowerShell:
#   uvicorn (FastAPI, :8000) + next dev (:3001)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $RootDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Error "Error: $VenvPython not found. Please set up .venv first."
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Starting Proofit Full-Stack Servers    " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

Write-Host "-> Starting FastAPI Backend on http://localhost:8000..." -ForegroundColor Yellow
$apiProcess = Start-Process -FilePath $VenvPython -ArgumentList "-m", "uvicorn", "api.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory $RootDir -PassThru

Write-Host "-> Starting Next.js Frontend on http://localhost:3001..." -ForegroundColor Yellow
$webProcess = Start-Process -FilePath "npm.cmd" -ArgumentList "run", "dev", "--", "-p", "3001" -WorkingDirectory (Join-Path $RootDir "web") -PassThru

Start-Sleep -Seconds 2

Write-Host ""
Write-Host "SUCCESS: Both servers are running!" -ForegroundColor Green
Write-Host "  * Frontend: http://localhost:3001" -ForegroundColor White
Write-Host "  * Backend:  http://localhost:8000" -ForegroundColor White
Write-Host ""
Write-Host "Press Ctrl+C to stop both servers." -ForegroundColor Gray

try {
    # Keep the script running until the user presses Ctrl+C or closes the window
    while ($true) {
        if ($apiProcess.HasExited) {
            Write-Warning "FastAPI backend stopped unexpectedly."
            break
        }
        if ($webProcess.HasExited) {
            Write-Warning "Next.js frontend stopped unexpectedly."
            break
        }
        Start-Sleep -Seconds 1
    }
}
finally {
    Write-Host "Stopping servers..." -ForegroundColor Yellow
    if ($apiProcess -and -not $apiProcess.HasExited) { Stop-Process -Id $apiProcess.Id -Force }
    if ($webProcess -and -not $webProcess.HasExited) { Stop-Process -Id $webProcess.Id -Force }
}

