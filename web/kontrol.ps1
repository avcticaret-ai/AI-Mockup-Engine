# Arayuz dosyalarinin butunlugunu kontrol eder.
#   cd C:\AI\AI-Mockup-Engine\web
#   .\kontrol.ps1

$ok = $true
Write-Host "`nArayuz dosya kontrolu`n" -ForegroundColor Cyan

foreach ($f in "index.html","app.js","style.css") {
    if (Test-Path $f) {
        $kb = [math]::Round((Get-Item $f).Length / 1KB, 1)
        Write-Host "  [tamam] $f  ($kb KB)" -ForegroundColor Green
    } else {
        Write-Host "  [YOK  ] $f" -ForegroundColor Red; $ok = $false
    }
}

if (Test-Path "app.js") {
    $t = Get-Content "app.js" -Raw
    Write-Host "`nParantez dengesi"
    foreach ($p in @(@("{","}","suslu"), @("(",")","normal"), @("[","]","kose"))) {
        $a = ([regex]::Matches($t, [regex]::Escape($p[0]))).Count
        $b = ([regex]::Matches($t, [regex]::Escape($p[1]))).Count
        if ($a -eq $b) {
            Write-Host "  [tamam] $($p[2]): $a" -ForegroundColor Green
        } else {
            Write-Host "  [HATA ] $($p[2]): $a acik, $b kapali  -> SOZDIZIMI HATASI" -ForegroundColor Red
            $ok = $false
        }
    }

    Write-Host "`nBeklenen fonksiyonlar"
    foreach ($fn in "connect","doRender","loadPlacement","layoutPlacement","applyFlipPreview") {
        if ($t -match "function\s+$fn\b" -or $t -match "$fn\s*=\s*(async\s*)?\(") {
            Write-Host "  [tamam] $fn" -ForegroundColor Green
        } else {
            Write-Host "  [YOK  ] $fn" -ForegroundColor Red; $ok = $false
        }
    }
}

Write-Host ""
if ($ok) {
    Write-Host "Dosyalar saglam. Sayfa hala bossa:" -ForegroundColor Green
    Write-Host "  1. Ctrl+Shift+R ile sert yenile (onbellek)"
    Write-Host "  2. F12 -> Console -> kirmizi hatayi oku"
    Write-Host "  3. .\teshis.ps1 ile sunucuyu kontrol et"
} else {
    Write-Host "SORUN VAR. Paketteki temiz kopyalari kur." -ForegroundColor Red
}
Write-Host ""
