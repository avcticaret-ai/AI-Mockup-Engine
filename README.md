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
