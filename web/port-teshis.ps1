# Port cakismasi teshisi
#   cd C:\AI\AI-Mockup-Engine\web
#   .\port-teshis.ps1

Write-Host "`nPort teshisi`n" -ForegroundColor Cyan

foreach ($port in 8000, 8001, 8080) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Host "  $port : bos" -ForegroundColor DarkGray
        continue
    }
    foreach ($cn in $conns) {
        $p = Get-Process -Id $cn.OwningProcess -ErrorAction SilentlyContinue
        Write-Host "  $port : $($cn.LocalAddress)  PID $($cn.OwningProcess)  $($p.ProcessName)" -ForegroundColor Yellow
        if ($p.Path) { Write-Host "         $($p.Path)" -ForegroundColor DarkGray }
        $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($cn.OwningProcess)" -ErrorAction SilentlyContinue).CommandLine
        if ($cmd) { Write-Host "         $cmd" -ForegroundColor DarkGray }
    }
}

Write-Host "`n8080 gercekten bizim sunucumuz mu?" -ForegroundColor Cyan
foreach ($u in "http://127.0.0.1:8080/health", "http://localhost:8080/health") {
    try {
        $r = Invoke-WebRequest $u -TimeoutSec 4 -UseBasicParsing
        $j = $r.Content | ConvertFrom-Json
        if ($j.api_version) {
            Write-Host "  [tamam] $u  ->  v$($j.api_version), $($j.model_count) model" -ForegroundColor Green
        } else {
            Write-Host "  [BASKA] $u  ->  200 ama api_version yok, ESKI server.py" -ForegroundColor Yellow
        }
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        if ($code) {
            Write-Host "  [HATA ] $u  ->  HTTP $code  (bu port BASKA bir uygulamada)" -ForegroundColor Red
        } else {
            Write-Host "  [HATA ] $u  ->  $($_.Exception.Message)" -ForegroundColor Red
        }
    }
}

Write-Host "`nCOZUM" -ForegroundColor Cyan
Write-Host "  8080'i baska bir uygulama tutuyorsa ya onu kapat"
Write-Host "  ya da motoru BASKA PORTTA baslat:"
Write-Host ""
Write-Host "    cd C:\AI\AI-Mockup-Engine"
Write-Host "    .\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8090"
Write-Host ""
Write-Host "  Sonra web\app.js icindeki ilk satiri guncelle:"
Write-Host '    const API = "http://127.0.0.1:8090";'
Write-Host ""
