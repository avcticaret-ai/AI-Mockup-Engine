$serverUrl = "http://localhost:8080"
Write-Host "`nParametre testi (PS 5.1 Uyumlu - Localhost)`n" -ForegroundColor Cyan

# Sunucu kontrolü
try {
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    $ver = Invoke-RestMethod -Uri "$serverUrl/api/v1/version" -UseBasicParsing -ErrorAction Stop
    Write-Host ("sunucu surumu : " + $ver.version)
    Write-Host ("yetenekler    : " + ($ver.capabilities -join ", "))
} catch {
    Write-Host "HATA: Sunucuya ulasilamiyor! ($serverUrl) -> $($_.Exception.Message)" -ForegroundColor Red
    exit
}

# Test Görseli Oluştur (1x1 PNG)
$dummyImg = [System.Convert]::FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
$imgPath = "$env:TEMP\test_dummy.png"
[System.IO.File]::WriteAllBytes($imgPath, $dummyImg)

Add-Type -AssemblyName System.Net.Http

function Send-TestRequest($params) {
    $client = New-Object System.Net.Http.HttpClient
    $content = New-Object System.Net.Http.MultipartFormDataContent

    # Görsel ekle
    $fileBytes = [System.IO.File]::ReadAllBytes($imgPath)
    $fileContent = New-Object System.Net.Http.ByteArrayContent(,$fileBytes)
    $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("image/png")
    $content.Add($fileContent, "design", "test.png")

    # Parametreleri ekle
    foreach ($key in $params.Keys) {
        $stringContent = New-Object System.Net.Http.StringContent($params[$key].ToString())
        $content.Add($stringContent, $key)
    }

    try {
        $response = $client.PostAsync("$serverUrl/api/v1/render", $content).Result
        $bytes = $response.Content.ReadAsByteArrayAsync().Result
        
        $received = ""
        if ($response.Headers.Contains("X-Render-Params")) {
            $received = ($response.Headers.GetValues("X-Render-Params") -join ", ")
        }
        
        return @{ Size = $bytes.Length; Received = $received; Success = $true }
    } catch {
        return @{ Error = $_.Exception.Message; Success = $false }
    } finally {
        $client.Dispose()
    }
}

$tests = @(
    @{ Name = "referans"; Params = @{ mock_id = "bella-canvas-3001/black" } },
    @{ Name = "scale 1.38"; Params = @{ mock_id = "bella-canvas-3001/black"; scale = 1.38 } },
    @{ Name = "displace 30"; Params = @{ mock_id = "bella-canvas-3001/black"; displace = 30 } },
    @{ Name = "shading 0.3"; Params = @{ mock_id = "bella-canvas-3001/black"; shading = 0.3 } },
    @{ Name = "flip_v"; Params = @{ mock_id = "bella-canvas-3001/black"; flip_v = "true" } },
    @{ Name = "offset_x 0.3"; Params = @{ mock_id = "bella-canvas-3001/black"; offset_x = 0.3 } }
)

Write-Host "test               boyut      sunucunun aldigi"
Write-Host "------------------------------------------------------------------------------"

foreach ($t in $tests) {
    $res = Send-TestRequest $t.Params
    if ($res.Success) {
        $nameFormatted = $t.Name.PadRight(18)
        $sizeFormatted = ("" + $res.Size).PadRight(10)
        Write-Host "$nameFormatted $sizeFormatted $($res.Received)"
    } else {
        Write-Host "$($t.Name) -> HATA: $($res.Error)" -ForegroundColor Red
    }
}
