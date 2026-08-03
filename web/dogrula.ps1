# Dosya surumlerini kontrol eder.
#   cd C:\AI\AI-Mockup-Engine\web
#   .\dogrula.ps1

$engine = Split-Path -Parent $PSScriptRoot
Write-Host "`nDosya surumu kontrolu`n" -ForegroundColor Cyan

$dosyalar = @{
    "server.py"                  = Join-Path $engine "server.py"
    "mockup_engine\pipeline.py"  = Join-Path $engine "mockup_engine\pipeline.py"
    "web\app.js"                 = Join-Path $PSScriptRoot "app.js"
}

$builds = @{}
foreach ($ad in $dosyalar.Keys) {
    $yol = $dosyalar[$ad]
    if (-not (Test-Path $yol)) {
        Write-Host ("  [YOK  ] {0,-28} dosya bulunamadi" -f $ad) -ForegroundColor Red
        $builds[$ad] = "YOK"; continue
    }
    $m = Select-String -Path $yol -Pattern 'BUILD\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($m) {
        $b = $m.Matches[0].Groups[1].Value
        $builds[$ad] = $b
        Write-Host ("  {0,-28} {1}" -f $ad, $b)
    } else {
        $builds[$ad] = "DAMGA YOK"
        Write-Host ("  [ESKI ] {0,-28} BUILD damgasi yok" -f $ad) -ForegroundColor Yellow
    }
}

$farkli = ($builds.Values | Select-Object -Unique)
Write-Host ""
if ($farkli.Count -eq 1 -and $farkli[0] -notin @("YOK","DAMGA YOK")) {
    Write-Host "TAMAM: tum dosyalar ayni surumde ($($farkli[0]))" -ForegroundColor Green
    Write-Host ""
    Write-Host "Sunucu calisiyorsa /health de kontrol et:"
    Write-Host "  curl http://127.0.0.1:8090/health"
    Write-Host "  build_ok true olmali."
} else {
    Write-Host "UYUMSUZ: dosyalar farkli surumlerde" -ForegroundColor Red
    Write-Host "Paketteki dosyalari TAMAMEN kopyala, sonra uvicorn'u yeniden baslat.`n"
}
Write-Host ""
