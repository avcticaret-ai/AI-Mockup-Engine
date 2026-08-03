# AI Mockup Studio -- render hatasi teshisi
#
#   cd C:\AI\AI-Mockup-Engine\web
#   .\teshis.ps1
#
# "Failed to fetch" tarayicinin genel ag hatasi; gercek sebebi
# gostermez. Bu script tarayiciyi devre disi birakip her katmani
# ayri ayri test eder.

$ErrorActionPreference = 'Continue'
$engine = Split-Path -Parent $PSScriptRoot
$API = "http://127.0.0.1:8080"

function Ok($m)   { Write-Host "  [tamam] $m" -ForegroundColor Green }
function Bad($m)  { Write-Host "  [HATA ] $m" -ForegroundColor Red }
function Note($m) { Write-Host "  $m" -ForegroundColor DarkGray }

Write-Host "`nAI Mockup Studio -- teshis`n" -ForegroundColor Cyan
Write-Host "motor: $engine`n"

# --- 1. Python ortami -------------------------------------------------
Write-Host "1. Python ortami"
$python = Join-Path $engine ".venv\Scripts\python.exe"
if (Test-Path $python) { Ok ".venv bulundu" }
else { Bad ".venv YOK -> $python"; Write-Host "`n  Cozum: .\setup.ps1`n"; exit 1 }

# --- 2. Bagimliliklar -------------------------------------------------
Write-Host "`n2. Bagimliliklar"
$deps = @{
    "fastapi"          = "FastAPI"
    "uvicorn"          = "Uvicorn"
    "multipart"        = "python-multipart  <-- DOSYA YUKLEME ICIN SART"
    "cv2"              = "OpenCV"
    "numpy"            = "NumPy"
}
$missing = @()
foreach ($mod in $deps.Keys) {
    & $python -c "import $mod" 2>$null
    if ($LASTEXITCODE -eq 0) { Ok $deps[$mod] }
    else { Bad $deps[$mod]; $missing += $mod }
}
if ($missing -contains "multipart") {
    Write-Host "`n  ==> BULUNDU: python-multipart eksik." -ForegroundColor Yellow
    Write-Host "      Bu paket olmadan GET istekleri calisir ama dosya"
    Write-Host "      yukleyen POST /render patlar. Belirtisi tam olarak"
    Write-Host "      'Failed to fetch'."
    Write-Host "`n  Cozum:" -ForegroundColor Cyan
    Write-Host "      cd $engine"
    Write-Host "      .\.venv\Scripts\python.exe -m pip install python-multipart`n"
    exit 1
}

# --- 3. Sunucu ayakta mi ---------------------------------------------
Write-Host "`n3. Sunucu"
try {
    $health = Invoke-RestMethod "$API/health" -TimeoutSec 5
    Ok "/health yanit veriyor"
    Note "durum      : $($health.status)"
    Note "model      : $($health.model_count)"
    Note "worker     : $($health.workers)"
    Note "max upload : $($health.max_upload_mb) MB"
    if ($health.model_count -eq 0) {
        Bad "kullanilabilir model yok"
        exit 1
    }
    $model = $health.models[0]
    Note "test modeli: $model"
} catch {
    Bad "/health yanit vermiyor -- sunucu kapali"
    Write-Host "`n  Cozum:" -ForegroundColor Cyan
    Write-Host "      cd $engine"
    Write-Host "      .\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8080`n"
    exit 1
}

# --- 4. Tasarim dosyasi ----------------------------------------------
Write-Host "`n4. Test tasarimi"
$design = Join-Path $engine "tasarimlar\test-design.png"
if (Test-Path $design) {
    Ok "test-design.png ($([math]::Round((Get-Item $design).Length/1KB)) KB)"
} else {
    Bad "test-design.png yok -> $design"
    exit 1
}

# --- 5. POST /render  (tarayici olmadan) -----------------------------
Write-Host "`n5. POST /render  -- tarayici devre disi"
$out = Join-Path $env:TEMP "teshis-mockup.png"
try {
    $form = @{
        design_file = Get-Item $design
        model_id    = $model
    }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    Invoke-RestMethod "$API/render" -Method Post -Form $form -OutFile $out -TimeoutSec 180
    $sw.Stop()

    if (Test-Path $out) {
        $kb = [math]::Round((Get-Item $out).Length / 1KB)
        Ok "render BASARILI  $kb KB  $($sw.Elapsed.TotalSeconds.ToString('0.0')) sn"
        Write-Host "`n  ==> Sunucu tarafi SORUNSUZ." -ForegroundColor Green
        Write-Host "      Sorun tarayicida. Kontrol et:"
        Write-Host "        - Arayuzu http://127.0.0.1:8001 gibi bir adresten actin mi?"
        Write-Host "          (file:// ile acmak CORS'u bozar)"
        Write-Host "        - F12 -> Console sekmesindeki kirmizi hatayi oku"
        Write-Host "        - F12 -> Network -> render istegine tikla, Status'e bak"
        Write-Host "        - Reklam engelleyici / eklenti kapatip dene"
        Write-Host "        - Farkli tarayici dene`n"
    } else {
        Bad "istek gecti ama dosya olusmadi"
    }
} catch {
    Bad "render BASARISIZ"
    Note $_.Exception.Message
    if ($_.ErrorDetails.Message) { Note $_.ErrorDetails.Message }
    Write-Host "`n  ==> Sunucu tarafinda hata var." -ForegroundColor Yellow
    Write-Host "      Uvicorn'u calistirdigin pencereye bak, traceback orada.`n"
    exit 1
}

# --- 6. CORS ---------------------------------------------------------
Write-Host "6. CORS"
try {
    $r = Invoke-WebRequest "$API/health" -Headers @{ Origin = "http://127.0.0.1:8001" } -TimeoutSec 5
    $acao = $r.Headers["access-control-allow-origin"]
    if ($acao) { Ok "access-control-allow-origin: $acao" }
    else { Bad "CORS basligi yok -- MOCKUP_CORS ayarini kontrol et" }
} catch {
    Bad "CORS kontrolu yapilamadi"
}

Write-Host "`nTeshis bitti.`n" -ForegroundColor Cyan
