# AI Mockup Engine - Windows kurulum
#
#   PowerShell'i normal kullanıcı olarak aç ve BU DOSYAYI ÇALIŞTIR:
#       cd C:\AI\mockup-engine\engine
#       .\setup.ps1
#
#   Komutları tek tek kopyalayacaksan ÖNCE cd yap. Geçen sefer
#   C:\WINDOWS\System32 içinden çalıştırıldığı için pip paketleri
#   yanlış Python'a kuruldu.

$ErrorActionPreference = 'Stop'

$ComfyRoot   = 'C:\AI\ComfyUI'
$EngineRoot  = $PSScriptRoot

Write-Host "`n=== 1. Yetim ComfyUI süreçleri ===" -ForegroundColor Cyan

$comfy = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -match 'main\.py' }

if ($comfy) {
    $comfy | Select-Object ProcessId, CommandLine | Format-Table -AutoSize
    Write-Host "Yukarıdaki süreçler kapatılsın mı? Yalnızca BİR tane çalışmalı." -ForegroundColor Yellow
    if ((Read-Host "Hepsini kapat (e/h)") -eq 'e') {
        $comfy | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep 2
        Write-Host "kapatıldı" -ForegroundColor Green
    }
} else {
    Write-Host "çalışan ComfyUI süreci yok" -ForegroundColor Green
}

Write-Host "`n=== 2. Yanlış yere kurulan torch ===" -ForegroundColor Cyan

# Bunlar ComfyUI'ın venv'ine DEĞİL, sistem Python 3.14'ünün kullanıcı
# klasörüne kuruldu. ComfyUI onları görmüyor; sadece disk yiyorlar.
$strayTorch = "$env:APPDATA\Python\Python314\site-packages\torch"
if (Test-Path $strayTorch) {
    $sizeGB = [math]::Round((Get-ChildItem $strayTorch -Recurse -File |
                Measure-Object Length -Sum).Sum / 1GB, 2)
    Write-Host "Kullanılmayan torch bulundu: $sizeGB GB" -ForegroundColor Yellow
    Write-Host "  $strayTorch"
    Write-Host "  (ComfyUI'ın venv'i etkilenmez)"
    if ((Read-Host "Silinsin mi (e/h)") -eq 'e') {
        & "$env:APPDATA\Python\Python314\Scripts\pip.exe" uninstall -y torch torchvision
    }
} else {
    Write-Host "temiz" -ForegroundColor Green
}

Write-Host "`n=== 3. ComfyUI model dosyaları ===" -ForegroundColor Cyan

$models = @{
    'diffusion_models\z_image_turbo_bf16.safetensors' = 'Z-Image Turbo (11.5 GB)'
    'text_encoders\qwen_3_4b.safetensors'             = 'Qwen3-4B metin kodlayıcı (7.5 GB)'
}
foreach ($rel in $models.Keys) {
    $full = Join-Path "$ComfyRoot\models" $rel
    if (Test-Path $full) {
        $gb = [math]::Round((Get-Item $full).Length / 1GB, 2)
        Write-Host ("  [var]  {0}  ({1} GB)" -f $models[$rel], $gb) -ForegroundColor Green
    } else {
        Write-Host ("  [YOK]  {0}" -f $models[$rel]) -ForegroundColor Red
        Write-Host ("         -> $full")
    }
}

Write-Host "`n=== 4. Mockup motoru venv ===" -ForegroundColor Cyan

# ComfyUI'ın venv'inden AYRI. Motorun torch'a ihtiyacı yok, sadece
# opencv/numpy/pillow. Ayrı tutmak ComfyUI'ı bozma riskini sıfırlıyor.
Set-Location $EngineRoot

if (-not (Test-Path "$EngineRoot\.venv")) {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { throw "python PATH'te bulunamadı." }
    & python -m venv .venv
    Write-Host "venv oluşturuldu" -ForegroundColor Green
} else {
    Write-Host "venv zaten var" -ForegroundColor Green
}

& "$EngineRoot\.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
& "$EngineRoot\.venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet
Write-Host "bağımlılıklar kuruldu" -ForegroundColor Green

Write-Host "`n=== 5. Doğrulama ===" -ForegroundColor Cyan

& "$EngineRoot\.venv\Scripts\python.exe" -c "import cv2, numpy, PIL; print('  opencv', cv2.__version__, '| numpy', numpy.__version__)"
& "$EngineRoot\.venv\Scripts\python.exe" tools\verify_preservation.py

Write-Host "`n=== Hazır ===" -ForegroundColor Green
Write-Host @"

Sıradaki adımlar:

  1. ComfyUI'ı TEK instance olarak başlat:
       cd $ComfyRoot
       .\venv\Scripts\python.exe main.py

  2. Başka bir PowerShell penceresinde:
       cd $EngineRoot
       .\.venv\Scripts\python.exe tools\generate_bases.py --check
       .\.venv\Scripts\python.exe tools\generate_bases.py --only female-front-001

  3. Üretilen base.png'yi %100 zoom'da göğüsten kontrol et,
     sonra:
       .\.venv\Scripts\python.exe tools\auto_mask.py bella-canvas-3001/female-front-001 --debug
       .\.venv\Scripts\python.exe tools\calibrate_quad.py bella-canvas-3001/female-front-001
       .\.venv\Scripts\python.exe tools\prepare_base.py  bella-canvas-3001/female-front-001
       .\.venv\Scripts\python.exe cli.py tasarimlar\test-design.png --model bella-canvas-3001/female-front-001

"@
