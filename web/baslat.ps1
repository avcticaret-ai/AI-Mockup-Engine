# AI Mockup Studio -- TEK SUNUCU, TEK PORT
#
#   cd C:\AI\AI-Mockup-Engine\web
#   .\baslat.ps1
#   .\baslat.ps1 -Port 8090        # port dolaysa
#
# Arayuz ve API ayni sunucudan geliyor. Ayri statik sunucuya gerek yok.

param([int]$Port = 8090)

$ErrorActionPreference = 'Stop'
$engine = Split-Path -Parent $PSScriptRoot

Write-Host "`nAI Mockup Studio" -ForegroundColor Cyan
Write-Host "motor: $engine`n"

$python = Join-Path $engine ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "HATA: .venv yok -> $python" -ForegroundColor Red
    Write-Host "Once: .\setup.ps1`n" -ForegroundColor Yellow
    exit 1
}

# --- port bos mu ---------------------------------------------------------
$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($conns) {
    foreach ($cn in $conns) {
        $p = Get-Process -Id $cn.OwningProcess -ErrorAction SilentlyContinue
        Write-Host "HATA: port $Port kullanimda" -ForegroundColor Red
        Write-Host "      PID $($cn.OwningProcess)  $($p.ProcessName)" -ForegroundColor Yellow
        if ($p.Path) { Write-Host "      $($p.Path)" -ForegroundColor DarkGray }
    }
    Write-Host "`n  Kapat:        Stop-Process -Id $($conns[0].OwningProcess) -Force" -ForegroundColor Cyan
    Write-Host "  Ya da:        .\baslat.ps1 -Port 8091`n" -ForegroundColor Cyan
    exit 1
}

# --- eski uvicorn surecleri ---------------------------------------------
$eski = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'uvicorn\s+server:app' }
if ($eski) {
    Write-Host "Calisan uvicorn surecleri bulundu:" -ForegroundColor Yellow
    $eski | ForEach-Object { Write-Host "  PID $($_.ProcessId)" }
    if ((Read-Host "Kapatilsin mi (e/h)") -eq 'e') {
        $eski | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep 2
        Write-Host "  kapatildi`n" -ForegroundColor Green
    }
}

# --- baslat --------------------------------------------------------------
Write-Host "Baslatiliyor  http://127.0.0.1:$Port" -ForegroundColor Green
$srv = Start-Process -FilePath $python `
    -ArgumentList "-m","uvicorn","server:app","--host","127.0.0.1","--port","$Port" `
    -WorkingDirectory $engine -PassThru

Start-Sleep -Seconds 3

try {
    $h = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 8
    Write-Host "  surum $($h.api_version) · $($h.model_count) model · $($h.workers) worker" -ForegroundColor Green

    if ($h.model_count -eq 0) {
        Write-Host "  UYARI: kullanilabilir model yok" -ForegroundColor Yellow
    }
    foreach ($i in $h.incomplete) {
        Write-Host "  eksik: $($i.model_id) -- $($i.reason)" -ForegroundColor DarkYellow
    }

    $ui = Invoke-WebRequest "http://127.0.0.1:$Port/" -TimeoutSec 5 -UseBasicParsing
    if ($ui.StatusCode -eq 200) {
        Write-Host "  arayuz hazir" -ForegroundColor Green
        Start-Process "http://127.0.0.1:$Port/"
    }
} catch {
    Write-Host "  HATA: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  Sunucu penceresinde traceback olabilir." -ForegroundColor Yellow
}

Write-Host "`nDurdur:  Stop-Process -Id $($srv.Id) -Force`n" -ForegroundColor DarkGray
