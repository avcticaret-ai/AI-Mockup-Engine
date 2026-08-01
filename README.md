# AI Mockup Engine — Faz 0

Bir PNG tasarımı, base model üzerine gerçekçi biçimde giydirir.
Diffusion yok, AI yok. Tasarımın pikselleri yalnızca geometrik olarak
dönüştürülüp ışıklandırılır — yazı ve ince detay birebir korunur.

## Kurulum

```bash
cd engine
pip install -r requirements.txt
```

## Çalıştırma

```bash
python cli.py tasarimlar/test-design.png --model test-model
```

Çıktı: `outputs/mockup.png`

```bash
python cli.py --list                          # base modelleri listele
python cli.py design.png --model test-model \
    --scale 0.85 --displace 20 --shading 0.7  # kalibrasyon
```

`--scale`, `--displace`, `--shading` `meta.json`'u geçici olarak ezer.
Değerleri beğendiğinde `meta.json`'a kalıcı yaz.

## Boru hattı

```
design.png (RGBA)
    │
    ├─ 1. warpPerspective   → print_quad'ın 4 köşesine oturt
    ├─ 2. remap             → displace.png gradyanıyla kumaş kıvrımı
    ├─ 3. multiply          → shading.png ile ışık/gölge
    ├─ 4. alpha             → print_mask.png ile baskı alanı dışını kes
    └─ 5. composite         → base.png üzerine bindir
    │
    v
outputs/mockup.png
```

Tüm ara hesap float32 [0,1]. uint8'e yalnızca en sonda dönülür.

## Base model varlıkları

`assets/base-library/<model-id>/` altında:

| Dosya | İçerik |
|---|---|
| `base.png` | Boş tişört giyen manken (RGB) |
| `garment_mask.png` | Tişörtün tamamı — renk değiştirmek için |
| `print_mask.png` | Baskı alanı, kenarları yumuşatılmış |
| `displace.png` | Kumaş kıvrım haritası |
| `shading.png` | Işık/gölge, **128 gri = nötr** |
| `meta.json` | Etiketler + compositor parametreleri |

Hepsi `base.png` ile aynı piksel boyutunda olmalı. Değilse `library.py`
yükleme anında hata verir — sessizce bozuk mockup üretmesindense
gürültülü patlaması daha iyi.

### meta.json

```jsonc
{
  "print_quad": [[488,486],[912,486],[922,1064],[478,1064]],
  //             sol-üst    sağ-üst   sağ-alt    sol-alt
  "design_scale": 0.92,        // baskı alanı doluluk oranı
  "displacement": {
    "strength": 14.0,          // piksel cinsinden kaydırma
    "blur": 9,                 // yüksek = geniş yumuşak kıvrım
    "mode": "gradient"         // "gradient" | "value"
  },
  "shading": { "strength": 0.85 }
}
```

`mode`: `gradient` kıvrım eğimini kullanır (kumaş için doğru olan).
`value` Photoshop'un Displace filtresi gibi davranır — hazır PSD
şablonlarından gelen haritalarla uyum için.

## Doğrulama

```bash
python tools/verify_preservation.py
```

Tasarımın yeniden çizilmediğini kanıtlar:

- Nötr gölge haritasında sapma **0.000000** olmalı
- Sıfır displacement'ta sapma **0.000000** olmalı
- Çıktıda kaynakta olmayan renkler yalnızca interpolasyon kaynaklı olmalı

Bu kontroller regresyon testi görevi görüyor. `compositor.py`'yi her
değiştirdiğinde çalıştır.

## test-model hakkında

`test-model` **sentetiktir** — gerçek fotoğraf değil, `tools/make_test_model.py`
tarafından prosedürel olarak üretilmiş bir tişört. Amacı motoru varlık
üretmeden önce uçtan uca doğrulamak. Yayınlanacak mockup için kullanma.

Yeniden üretmek için:

```bash
python tools/make_test_model.py
python tools/make_test_design.py
```

## Gerçek base modele geçiş

`test-model` kalitesini onayladıktan sonra sıra gerçek varlıkta. Her
gerçek model için gereken:

1. **base.png** — mankenin boş tişört giydiği yüksek çözünürlüklü görsel
2. **garment_mask / print_mask** — segmentasyon veya elle maskeleme
3. **displace.png** — tişört bölgesinin gri tonlaması, yüksek geçiren filtre
4. **shading.png** — aynı gri tonlamanın düşük frekanslı bileşeni (ağır blur)
5. **print_quad** — göğüsteki baskı alanının 4 köşesi, elle işaretlenir

3, 4 ve 5 yarı otomatikleştirilebilir (`tools/prepare_base.py` — henüz yok).
Adım 5 model başına ~2 dakika elle iş demek; 30 model için bir saat.

## Bilinen sınırlar

- **Düzlemsel warp.** Kupa ve telefon kılıfı gibi silindirik yüzeyler bu
  4 noktalı perspektifle doğru çıkmaz, ayrı bir warp modeli gerekir.
- **Tek baskı alanı.** Ön + arka aynı anda üretilmiyor; her biri ayrı
  base model olarak tanımlanmalı.
- **Renk değiştirme yok.** `garment_mask.png` üretiliyor ve yükleniyor
  ama `recolor.py` henüz yazılmadı — Faz 1'de.

---

## Faz 0.5 — gerçek base model ekleme

Kütüphane artık iç içe: `base-library/<marka-model>/<varyant>/`.
Model id göreli yoldur, örn. `bella-canvas-3001/female-front-001`.
Düz yerleşim (`test-model`) çalışmaya devam eder.

### Akış

```bash
# 1. base.png klasöre kaydedilir (Nim çıktısı / satın alınan / çekilen)
# 2. garment_mask.png elle hazırlanır (GIMP, ~10 dk)

python tools/calibrate_quad.py bella-canvas-3001/female-front-001
python tools/prepare_base.py  bella-canvas-3001/female-front-001
python cli.py tasarim.png --model bella-canvas-3001/female-front-001
```

Elle yapılan tek iş `garment_mask.png` ve 4 köşe tıklaması.
`print_mask`, `displace` ve `shading` `prepare_base.py` tarafından türetilir.

### Türetme nasıl çalışıyor

`displace` luminance'ın yüksek geçiren bileşeni: genel aydınlatma (çok
kaba) ve kumaş dokusu (çok ince) atılır, orta frekanslı kıvrım yapısı
kalır.

`shading` alçak geçiren bileşen. **Nötr nokta sabit 128 değil, giysinin
kendi ortalama parlaklığıdır.** Beyaz tişörtün ortalaması ~212 çıkıyor;
128 kabul edilirse tüm tasarım sistematik olarak aydınlanır.

Kalibrasyon anahtarları: `--structure` kıvrım/ışık ayrım eşiği,
`--shading-gain` gölge kontrastı, `--inset` baskı maskesinin kenardan
içeri çekilmesi. Hepsi görsel yüksekliğinin oranı olarak verilir, yani
1400px test görselinde ayarlanan değer 4000px fotoğrafta da çalışır.

`prepare_base.py` kıvrım standart sapması 6'nın altındaysa uyarır —
bu, base fotoğrafın ışığının çok düz olduğu ve displacement'ın etkisiz
kalacağı anlamına gelir.

### meta.json köken alanları

`source`, `source_detail`, `verified_garment`, `publishable` alanları
`calibrate_quad.py` tarafından otomatik ekleniyor. Kütüphane büyüdüğünde
hangi asset'in AI üretimi hangisinin gerçek fotoğraf olduğunu ayırt
etmenin tek yolu bu — ve Etsy'ye hangi görselleri koyabileceğini bu
belirliyor.

---

## ComfyUI entegrasyonu (Faz 1)

Base görselleri artık Nim yerine lokalde, Z-Image Turbo ile üretiliyor.
16 GB VRAM ile sınırsız ve ücretsiz.

```
comfybridge/
  client.py                       ComfyUI HTTP API istemcisi (stdlib, ek bağımlılık yok)
  variants.json                   üretilecek varyantlar + istem şablonu
  workflows/
    zimage_blank_tee.json         API formatında iş akışı (10 node)
```

### İki ayrı Python ortamı

| Ortam | Konum | İçerik |
|---|---|---|
| ComfyUI | `C:\AI\ComfyUI\venv` | torch, ComfyUI bağımlılıkları |
| Mockup motoru | `engine\.venv` | opencv, numpy, pillow |

Motorun torch'a ihtiyacı yok. Ayrı tutmak ComfyUI'ı bozma riskini
ortadan kaldırıyor — bir pip komutu asla diğerini etkilemez.

### Toplu üretim

```powershell
.\.venv\Scripts\python.exe tools\generate_bases.py --check   # ortamı doğrula
.\.venv\Scripts\python.exe tools\generate_bases.py --list    # varyantları gör
.\.venv\Scripts\python.exe tools\generate_bases.py           # hepsini üret
```

`--check` ComfyUI'a hiç iş göndermeden üç şeyi doğrular: iş akışının
bağlantı bütünlüğü, ComfyUI'ın ayakta olması, ve gereken node tiplerinin
kurulu olması. "Neden hiçbir şey olmuyor" turu hata ayıklamayı bitiriyor.

### İstem neden böyle yazıldı

Z-Image Turbo damıtılmış bir model, `cfg=1.0` ile çalışıyor — guidance
kapalı, **negatif istem pratikte etkisiz**. "no logo, no print" gibi
kısıtları negatife yazmak hiçbir şey yapmaz.

Bu yüzden `comfybridge/variants.json` içindeki şablonda tüm kısıtlar pozitif istemin
içinde olumlu ifadeyle yer alıyor: `plain unprinted`, `blank empty chest`,
`smooth undecorated fabric`.

Işık tarifi de kritik. `displace.png` ve `shading.png` fotoğraftaki
gölgelerden türetiliyor — düz ışık, boş harita, etkisiz displacement
demek. Şablon yönlü yan ışık istiyor.

### Otomatik giysi maskesi

Kütüphanedeki tek elle iş buydu. 30 model için ~5 saat GIMP demekti.

```powershell
.\.venv\Scripts\python.exe tools\auto_mask.py bella-canvas-3001/female-front-001 --debug
```

**classic** (varsayılan, ek bağımlılık yok): fon satır bazlı renk modeliyle
bulunur, kişi = fon değil, kişi içinde tişört = düşük doygunluk + yüksek
parlaklık. Ten daha doygun (S~90), saç daha karanlık — ikisi de eşiğin
dışında kalır. Kontrollü stüdyo çekimi için tasarlandı.

**cloth** (`pip install rembg onnxruntime`): u2net_cloth_seg ile ML
segmentasyon. Renkli tişörtte ve karmaşık arka planda daha iyi.

`--debug` yeşil kaplamalı bir kontrol görseli yazar. Maske kare alanının
%15-70'i dışında kalırsa araç uyarır; bu aralık dışı neredeyse her zaman
kötü segmentasyon demektir.

**Sonucu her zaman gözle kontrol et.** Yaka, koltuk altı ve etek çizgisi
kritik bölgeler.

### Tam akış

```
tools/generate_bases.py     ComfyUI -> base.png + meta.json
tools/auto_mask.py          base.png -> garment_mask.png
tools/calibrate_quad.py     4 tıklama -> print_quad
tools/prepare_base.py       -> print_mask.png, displace.png, shading.png
cli.py                      tasarım + model -> mockup
```

Model başına elle iş: bir gözle kontrol + dört tıklama. Yaklaşık 2 dakika.

### Printify kataloğunun tamamına genişletme

`comfybridge/variants.json` içindeki `product` alanı ve kütüphanedeki iç içe yapı
bunun için tasarlandı:

```
assets/base-library/
  bella-canvas-3001/female-front-001/
  gildan-5000/male-front-001/
  ...
```

Tişört dışına çıkarken tek uyarı: **kupa ve telefon kılıfı silindirik
yüzeydir.** `compositor.py`'deki 4 noktalı düzlemsel perspektif onlarda
doğru sonuç vermez, ayrı bir warp modeli gerekir. Düz ürünler (tişört,
hoodie, çanta, poster) mevcut motorla çalışır.

---

## Dosya yapısı — ZORUNLU düzen

Motorun tamamı `Path(__file__).parent` ile göreli yol kuruyor. Bu düzen
bozulursa hiçbir araç çalışmaz, ve hatalar anlaşılmaz `ImportError` veya
"model bulunamadı" olarak çıkar.

`check_layout.py`'nin bulunduğu klasör **motorun köküdür**. Altındaki
yapı şudur:

```
<motor-kökü>/                      ← burası AI-Mockup-Engine olabilir
├── check_layout.py                ← ilk çalıştırılacak şey
├── cli.py
├── setup.ps1
├── requirements.txt
├── README.md
│
├── mockup_engine/                 ← compositor paketi
│   ├── __init__.py
│   ├── compositor.py
│   ├── library.py
│   └── pipeline.py
│
├── comfybridge/                   ← ComfyUI köprüsü
│   ├── __init__.py
│   ├── client.py
│   ├── variants.json              ← DOSYA, klasör değil
│   └── workflows/
│       └── zimage_blank_tee.json
│
├── tools/
│   ├── auto_mask.py
│   ├── calibrate_quad.py
│   ├── generate_bases.py
│   ├── prepare_base.py
│   ├── verify_preservation.py
│   ├── make_test_model.py
│   └── make_test_design.py
│
├── assets/
│   └── base-library/              ← bu katman ATLANMAZ
│       ├── test-model/
│       └── bella-canvas-3001/
│           └── female-front-001/
│
├── tasarimlar/                    ← girdi PNG'leri
└── outputs/                       ← üretilen mockup'lar
```

### Bulunmaması gerekenler

| Klasör | Neden yanlış |
|---|---|
| `comfy/` | ComfyUI'ın kendi `comfy` paketiyle çakışır → `comfybridge/` |
| `variants/` | `comfybridge/variants.json` bir dosyadır |
| `workflows/` | kökte değil, `comfybridge/` içinde |
| `library/` | model kütüphanesi `assets/base-library/` altında |
| `templates/` | kullanılmıyor |
| iç içe `engine/` | kök zaten `check_layout.py`'nin yeri |

### Doğrulama

```powershell
python check_layout.py
```

Yedi şeyi kontrol eder: zorunlu dosyalar, zorunlu klasörler, yanlış
yerleştirme izleri, importlar, ComfyUI iş akışının bağlantı bütünlüğü,
base model kütüphanesinin durumu, ve bağımlılıklar.

Herhangi bir şey çalıştırmadan önce bunu çalıştır ve **"Yapı doğru"**
çıktısını gör.

---

## Renk değiştirme (Faz 1)

`mockup_engine/recolor.py` — beş renk tek beyaz base'den türetiliyor.

```python
from mockup_engine import generate_mockup
generate_mockup(design, model_id, library, out, color="navy")
```

`color=None` (varsayılan) → recolor atlanır, davranış eskisiyle **bit bit
aynı**. Mevcut kalibre edilmiş `meta.json` değerleri ve regresyon
testleri etkilenmez.

### compositor.py'ye dokunulmadı

Recolor base görseli üzerinde ön işlemdir, tasarım hattına girmez:

```
base.png ──recolor(garment_mask, renk)──> renkli base
                                              │
design.png ──warp──displace──shade──mask──composite──> mockup
                    ↑ bu beş adım değişmedi
```

`shading.png` yeniden hesaplanmıyor: tişört siyaha dönse de baskının
üzerine düşen **göreli** ışık aynı kalıyor.

### Neden CIELAB, neden çarpma değil

İlk tasarım linear uzayda difüz/spekuler ayrımı öngörüyordu. Uygulamadan
önce ölçüldü ve yetersiz çıktı. `test-model` üzerindeki sonuçlar:

| Renk | Yöntem | L* yayılımı | Base'e oran | Sonuç |
|---|---|---|---|---|
| black | multiply | 6.39 | 0.30 | **yetersiz** |
| black | lab | 18.95 | 0.89 | geçti |
| navy | multiply | 7.75 | 0.36 | **yetersiz** |
| navy | lab | 19.78 | 0.93 | geçti |

Sebep gamma'nın yönü: linear uzayda çarpma koyu hedefte kıvrım bilgisini
sıfıra doğru sıkıştırıyor, sRGB'ye dönüşteki gamma genişlemesi telafi
etmeye yetmiyor.

Uygulanan yöntem CIELAB'da kontrast koruma:

```
L*_çıktı = L*_hedef + (L*_base − L*_ortalama) × kontrast
```

L* algısal olarak düzgün olduğu için aynı yayılım koyu ve açık renkte
aynı miktarda kıvrım görünürlüğü demek. cv2'nin Lab dönüşümü
sRGB → linear → XYZ → Lab zincirini kendisi yaptığı için istenen linear
workflow bedava geliyor.

`method="multiply"` karşılaştırma için duruyor. Üretimde kullanma.

### preserve_spread

Hedef L*, base ortalamasından uzaksa kırpma oluşur. Beyaz base üzerine
beyaz uygularken hedef L*=97, base ortalaması 85 → giysinin **%33.8'i**
tavanda doyup düzleşiyordu.

`preserve_spread=True` (varsayılan) bu durumda hedef L*'ı kaydırıp
yayılımı koruyor. Kıvrım görünürlüğü, hedef parlaklığı birebir
tutmaktan daha değerli.

| Renk | preserve_spread yok | var |
|---|---|---|
| white | yayılım 13.44, tavan kırpma %33.8 | yayılım 21.41, kırpma %2.0 |

### Renk presetleri

Gerçek kumaş değerleri, saf renkler değil. Saf `#000000` difüz terimi
sıfırlar; gerçek siyah tişört ~`#1F1F1F`.

| Preset | sRGB |
|---|---|
| white | `#F7F7F5` |
| buttery | `#EFDFA8` |
| light_green | `#9CAF88` |
| black | `#1F1F1F` |
| navy | `#232F3E` |

`#RRGGBB` doğrudan da verilebilir.

### Ölçüm

```bash
python tools/verify_recolor.py test-model
python tools/verify_recolor.py <model> --write   # görselleri de yaz
```

Karar ölçütü: bir rengin L* yayılımı, base'in yayılımının **%60'ının**
altına düşerse kıvrımlar düz okunur → o renk için ayrı koyu base gerekir.

Araç çıkış kodu 2 döndürürse tek base ailesi yetersiz demektir.
`compositor.py` veya `recolor.py` değiştiğinde çalıştır.

---

## HTTP API (server.py)

n8n, Next.js veya başka bir otomasyondan tetiklemek için.

```bash
pip install -r requirements.txt
uvicorn server:app --host 127.0.0.1 --port 8080 --reload
```

Etkileşimli dokümantasyon: http://127.0.0.1:8080/docs

**`server.py` hiçbir görüntü işleme mantığı içermez.** Tek işi HTTP
isteğini `mockup_engine.generate_mockup()` çağrısına çevirmek. Böylece
API ve CLI birebir aynı çıktıyı üretir; compositor, recolor ve kütüphane
mantığı tek yerde kalır.

### Uç noktalar

| Yöntem | Yol | İş |
|---|---|---|
| GET | `/health` | durum + kütüphanedeki modeller |
| GET | `/colors` | renk presetleri |
| POST | `/render` | tek mockup (multipart **veya** JSON) |
| POST | `/batch-render` | model × renk matrisi |
| GET | `/outputs/{job_id}/{dosya}` | toplu çıktıyı indir |
| GET | `/outputs/{job_id}.zip` | hepsini zip olarak indir |

### Örnekler

```bash
# sağlık
curl http://127.0.0.1:8080/health

# tek render, dosya yükleyerek
curl -X POST http://127.0.0.1:8080/render \
  -F "design_file=@tasarimlar/test-design.png" \
  -F "model_id=test-model" \
  -F "color=navy" \
  -o mockup.png

# kalibrasyon ezmeleriyle
curl -X POST http://127.0.0.1:8080/render \
  -F "design_file=@tasarim.png" \
  -F "model_id=test-model" \
  -F "scale=0.85" -F "displace=20" -F "shading=0.7" \
  -o mockup.png

# JSON + base64, yanıt da JSON
curl -X POST http://127.0.0.1:8080/render \
  -H "Content-Type: application/json" \
  -d "{\"design_base64\":\"$(base64 -w0 tasarim.png)\",
       \"model_id\":\"test-model\",\"color\":\"black\",
       \"response_mode\":\"json\"}"

# toplu: 1 model x 5 renk
curl -X POST http://127.0.0.1:8080/batch-render \
  -H "Content-Type: application/json" \
  -d "{\"design_base64\":\"$(base64 -w0 tasarim.png)\",
       \"model_ids\":[\"test-model\"],
       \"colors\":[\"white\",\"buttery\",\"light_green\",\"black\",\"navy\"]}"
```

```python
import requests

# tek render
r = requests.post("http://127.0.0.1:8080/render",
                  files={"design_file": open("tasarim.png", "rb")},
                  data={"model_id": "test-model", "color": "navy"})
open("mockup.png", "wb").write(r.content)

# toplu render + zip indirme
import base64
design = base64.b64encode(open("tasarim.png", "rb").read()).decode()
job = requests.post("http://127.0.0.1:8080/batch-render", json={
    "design_base64": design,
    "model_ids": ["test-model"],
    "colors": ["white", "black", "navy"],
}).json()

print(job["succeeded"], "/", job["requested"])
z = requests.get("http://127.0.0.1:8080" + job["zip_url"])
open("mockups.zip", "wb").write(z.content)
```

### Güvenlik

**SSRF koruması.** `design_url` açık bir kapıdır: kötü niyetli bir istek
sunucunun iç ağına yönlendirilebilir — bulut metadata servisi
(169.254.169.254), yereldeki ComfyUI (127.0.0.1:8188), LAN'daki başka
servisler. Şema http/https ile sınırlı ve host'un çözümlenen **tüm**
adresleri özel/loopback/link-local kontrolünden geçiyor.

Tamamen kapatmak için: `MOCKUP_ALLOW_URL_FETCH=0`

**Diğer kontroller:** yükleme boyutu sınırı, `cv2.imdecode` ile gerçek
görüntü doğrulaması (uzantıya ve content-type'a güvenilmiyor), çıktı
indirmede yol aşımı koruması, toplu istek adet sınırı, geçici dosyaların
`BackgroundTask` ile otomatik temizliği, iş klasörleri için TTL.

`allow_origins="*"` yalnızca yerel geliştirme içindir. Dışa açacaksan
`MOCKUP_CORS` ile daralt ve önüne kimlik doğrulama koy — **bu API'de
kimlik doğrulama yoktur.**

### Ayarlar (ortam değişkeni)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `MOCKUP_WORKERS` | 4 | eşzamanlı render sayısı |
| `MOCKUP_MAX_UPLOAD_MB` | 40 | yükleme boyut sınırı |
| `MOCKUP_MAX_BATCH` | 50 | toplu istekte azami öğe |
| `MOCKUP_JOB_TTL` | 3600 | çıktıların saklanma süresi (sn) |
| `MOCKUP_ALLOW_URL_FETCH` | 1 | `design_url` desteği |
| `MOCKUP_CORS` | `*` | izinli origin listesi |

### Neden ThreadPool, ProcessPool değil

OpenCV ve NumPy ağır işlemlerde GIL'i bırakıyor, yani thread'ler gerçek
paralellik veriyor. ProcessPool Windows'ta spawn + pickle maliyeti
getirir ve `--reload` ile sorun çıkarır.

### Bilinen performans sınırı

Ölçüm (1400×1800 base, `test-model`):

```
load_model()       137 ms   (%6)
saf compositing   2005 ms   (%94)
toplam            2141 ms
```

Darboğaz model yükleme değil, compositing. `cv2.remap` tuvalin
tamamını işliyor ama tasarım karenin ~%10'unu kaplıyor. Displacement'ı
baskı alanının sınırlayıcı kutusuyla sınırlamak 5-8× hızlanma verir.
25 mockup şu an ~54 saniye.

---

## Toplu üretim (batch.py)

Tasarım × model × renk çapraz çarpımı.

```bash
python batch.py tasarim.png --colors white,black,navy
python batch.py --designs tasarimlar --models all --colors all
python batch.py --designs tasarimlar --product bella-canvas-3001 --colors all
python batch.py --designs tasarimlar --colors all --dry-run   # sadece plan
```

Çıktı: `outputs/batch/<zaman-damgasi>/<tasarim-adi>/<model>-<renk>.png`
Yanında `manifest.json` — hangi dosya hangi model/renk, süreler, hatalar.

### Renkler klasör değildir

`recolor.py` beş rengi **çalışma anında** tek beyaz base'den türetiyor.
Kütüphanede renk başına asset tutulmuyor. Model id ise kütüphaneye göre
göreli yoldur:

```
--models bella-canvas-3001/pose-01-front     doğru
--models bella-canvas-3001                   yanlış (bu bir ürün, model değil)
--product bella-canvas-3001                  ürünün tüm pozları için bunu kullan
```

### Paralellik ayarı

OpenCV **zaten kendi içinde çok çekirdekli**. N worker × her biri tüm
çekirdekler = thread boğuşması. Ölçüm (tek çekirdekli makine, 5 mockup):

| Worker | OpenCV thread | Süre |
|---|---|---|
| 4 | otomatik | 26.5 sn |
| 1 | 1 | 9.7 sn |

`batch.py` ve `server.py` artık worker sayısını çekirdek sayısına göre
belirliyor ve OpenCV thread'lerini worker'lara bölüyor. Elle ezmek için
`--workers` / `MOCKUP_WORKERS`.

---

## Etsy çıktısı (export_etsy.py)

```bash
python tools/export_etsy.py outputs/batch/<zaman-damgasi>
python tools/export_etsy.py <klasör> --shape portrait --format jpg
```

Etsy gereksinimleri (2026): en az **2000 piksel kısa kenar**, 1:1 kare
veya 4:5 dikey, **sRGB**, JPG/PNG.

Araç kırpma yapmaz — mockup'ın kenarını kesmek modeli budayabilir.
Bunun yerine fon rengini kenar bandından örnekleyip dolgu yapar.

### Çözünürlük — dikkat

Kaynak 2000 pikselin altındaysa araç büyütür ve **uyarır.** Doğru çözüm
burada büyütmek değil, base asset'i baştan yeterli çözünürlükte
üretmektir: tasarım base çözünürlüğünde compose ediliyor, mockup'ı
sonradan büyütmek kaybolan detayı geri getirmez.

Bu yüzden `comfybridge/variants.json` çözünürlüğü **1024×1536'dan
1536×2048'e** çıkarıldı. Kalan büyütme ~%30, Lanczos ile kabul
edilebilir. Daha yükseğe çıkacaksan Z-Image çıktısının keskinliğini
gözle kontrol et — model ~1024 civarında eğitildi.

---

## İlk publishable asset

Gerçek Bella Canvas 3001 fotoğrafından yayınlanabilir asset üretmek için:
**`SOP-GercekBC3001.md`**

Hedef klasör `assets/base-library/bella-canvas-3001/female-front-001/`
hazır bekliyor — `meta.json` fotoğraf yoluna göre ayarlandı
(`source: photographed`), `print_quad` boş ve ölçümle doldurulacak.

Yöntem `kalibrasyon/bella-ref` üzerinde uçtan uca doğrulandı: 34 kontrol,
0 hata. Gerçek fotoğrafta değişecek tek şey kalibrasyon değerleridir
(`displacement.strength`, `shading.strength`) — giyilmiş kumaş düz
çekimden daha çok kırışır ve yönlü ışık gölge aralığını genişletir.

### Kabul kriterleri

`publishable: true` yapmadan önce hepsi geçmeli:

| Ölçüm | Geçti | Uyarı | Hata |
|---|---|---|---|
| `garment_mask` kaplama | %25–60 | — | dışı |
| Kıvrım std | > 6 (ideal > 15) | — | ≤ 6 |
| **Kıvrım/gürültü oranı** | **≥ 1.50** | **1.20 – 1.50** | **< 1.20** |
| Gölge aralığı | > 50 seviye | 20–50 | ≤ 20 |
| Baskı alanı giysi içinde | ≥ %99.5 | %95–99.5 | < %95 |
| `print_mask` giysi dışına taşan | 0 piksel | — | > 0 |
| Render: baskı alanı dışında değişim | 0 piksel | — | > 0 |

Son ikisi sıfır tolerans — maskeleme doğruluğunu ölçüyorlar.

**Uyarı asset'i geçersiz kılmaz.** Çıkış kodu yalnızca hata durumunda
1 döner; uyarılı bir asset `publishable` olmaya devam eder.

Kıvrım/gürültü ara bandı (1.20–1.50) JPEG sıkıştırması veya düşük
çözünürlük yüzünden sinyali zayıflamış ama kullanılabilir asset'ler
için. Bu eşiklerin regresyon testi:

```bash
python tools/test_fold_noise_tiers.py
```

### `--scale` davranışı

`design_scale` tasarımın baskı alanı içindeki doluluk oranıdır.
`1.0` = alanı tamamen kaplar.

**1.0 üzeri değerler** tasarımı baskı alanının dışına taşırır ve
`print_mask` fazlalığı kırpar. Teknik olarak çalışır, ama `print_quad`
gerçek 12×16 inçten türetildiyse basılamayacak bir mockup üretir —
tasarım gerçekte o kadar büyük basılamaz.

`--scale` üç giriş noktasının hepsinde çalışır ve `meta.json`'daki değeri
geçici olarak ezer:

```bash
python cli.py tasarim.png --model <model> --scale 0.85
python batch.py --designs tasarimlar --models <model> --scale 0.85
curl -F "scale=0.85" ...     # API, 0 < scale <= 2.0
```

### print_quad: otomatik + manuel

`tools/derive_quad.py` baskı alanını gövde genişliğinden oran yoluyla
hesaplar. Gerçek fotoğraflarda perspektif, drape veya yaka çukurunun
maskeden tespit edilememesi konumu kaydırabiliyor; o durumda koordinat
elle verilir.

```bash
# otomatik
python tools/derive_quad.py bella-canvas-3001/female-front-001
python tools/derive_quad.py <model> --size L
python tools/derive_quad.py <model> --dry-run

# manuel override -- DÖRT kenar birden
python tools/derive_quad.py bella-canvas-3001/female-front-004 \
    --left 1200 --top 350 --right 1650 --bottom 950
```

Manuel verilirse otomatik hesap tamamen atlanır, önizleme yine üretilir.
`meta.json` içine `quad_source` yazılır: `"auto"` veya `"manual"`.

İş akışı:

```
derive_quad.py <model>              otomatik dene
_quad_preview.png                   gözle bak
derive_quad.py <model> --left ...   yanlışsa düzelt
prepare_base.py <model> --force     haritaları yenile
verify_asset.py <model> --render    doğrula
```

`prepare_base.py --force` şart — `print_mask.png` quad'dan türetiliyor,
quad değişince yenilenmezse eski maske kalır.

#### Taşma toleransı

`verify_asset.py` baskı alanının giysi içinde kalan **alan yüzdesini**
ölçer (eskiden yalnızca dört köşeye bakıyordu):

| İçeride | Sonuç |
|---|---|
| ≥ %99.5 | geçti |
| %95 – %99.5 | geçti + uyarı — `print_mask` zaten kırpıyor |
| < %95 | hata |
