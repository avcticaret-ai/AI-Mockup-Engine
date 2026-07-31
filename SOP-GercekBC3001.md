# SOP — İlk Publishable Bella Canvas 3001 Asset'i

**Hedef:** `assets/base-library/bella-canvas-3001/female-front-001/`
**Kaynak:** Gerçek BC3001'in kendi çektiğin fotoğrafı. AI üretimi değil.

Bu belge kalibrasyon asset'i (`kalibrasyon/bella-ref`) üzerinde uçtan uca
doğrulanmış yöntemi gerçek fotoğrafa uyarlar. Yöntem kanıtlandı; burada
değişen tek şey girdinin gerçek ve yayınlanabilir olması.

---

## 0 — Kalibrasyon asset'inden ne taşınır, ne taşınmaz

| Taşınır | Taşınmaz |
|---|---|
| `--method cloth` tercihi | `print_quad` koordinatları |
| Quad'ı ölçerek türetme yöntemi | `displacement.strength` |
| Kabul kriteri eşikleri | `shading.strength` |
| Doğrulama kontrol listesi | `classic` tolerance değerleri |

**Neden taşınmaz:** Kalibrasyon görseli düz çekimdi (flat lay), gerçek
fotoğrafta tişört bir insanın üzerinde olacak. Üç ölçülebilir fark:

- **Kıvrımlar güçlenir.** Vücut üzerindeki kumaş düz çekimden çok daha
  fazla kırışır. `displacement.strength` muhtemelen düşecek.
- **Gölge aralığı genişler.** Kalibrasyonda 31 seviyeydi (106–137).
  Yönlü yan ışıkla çekilmiş bir fotoğrafta 50+ olmalı.
- **Ten girer.** Kalibrasyon görselinde ten yoktu. Maske artık ten/kumaş
  ayrımı da yapmak zorunda.

---

## 1 — Çekim şartnamesi

**Bu adım geri dönüşü en pahalı olan adımdır.** Fotoğraf yetersizse
kalibrasyonla kurtarılmaz, yeniden çekilir.

### Zorunlu

| Şart | Neden |
|---|---|
| **Yönlü yan ışık, ~45°** | Kıvrım gölgesi olmadan displacement haritası boş çıkar |
| **Kısa kenar ≥ 2400 px** | Etsy 2000 istiyor; kırpma payı gerekir |
| **Kontrastlı fon** | Kalibrasyonda ayrım 2.26 L\* idi ve `classic` çöktü |
| **Kollar gövdeden ayrık** | Koltuk altı maskesi temiz çıksın |
| **Doğal, hafif asimetrik duruş** | Dimdik duruş kumaşı düzleştirir |
| **Göğüs bölgesi temiz** | Saç, kolye, çanta askısı maskeyi bozar |

### Yasak

- Beyaz tişört + beyaz/açık gri duvar
- Düz, gölgesiz ışık (tepe lambası, halka lamba, flaş)
- Ütülenmiş kırışıksız kumaş
- Göğse düşen saç

### Işık kurulumu

Pencere ışığı yeterli. Model pencereye 45 derece dönük dursun, karşı
tarafa beyaz bir karton koyup gölgeyi hafifçe doldur — tamamen doldurma,
gölge kalmalı.

### Model onayı

Gerçek bir kişiyi fotoğraflıyorsan ticari kullanım için yazılı onay al.
Basit bir metin yeterli ama `meta.json > source_detail` alanına
onayın alındığını yaz.

---

## 2 — Ön kontrol (asset üretmeden önce)

Fotoğrafı klasöre koymadan önce üç sayıyı ölç. Beş adım ilerledikten
sonra sorun keşfetmektense burada öğren.

```powershell
cd C:\AI\AI-Mockup-Engine
.\.venv\Scripts\Activate.ps1
```

```powershell
python -c "import cv2,numpy as np; p=r'C:\yol\foto.jpg'; i=cv2.imread(p); h,w=i.shape[:2]; L=cv2.cvtColor(i.astype(np.float32)/255,cv2.COLOR_BGR2LAB)[...,0]; print(f'boyut {w}x{h}  kisa kenar {min(w,h)}'); print(f'kare L* std {L.std():.2f}')"
```

| Ölçüm | Kabul | Yetersizse |
|---|---|---|
| Kısa kenar | ≥ 2400 | Daha yüksek çözünürlükte çek |
| Kare L\* std | > 8 | Işık düz, yeniden çek |

Bu ön kontrol kaba bir eleme. Asıl karar Adım 6'daki kıvrım std'sinde
verilir.

---

## 3 — base.png

```powershell
Copy-Item C:\yol\foto.jpg assets\base-library\bella-canvas-3001\female-front-001\base.png
```

`.jpg` uzantısını değiştirmek yetmez, gerçekten PNG'ye çevir.

```powershell
python -c "import cv2; i=cv2.imread(r'assets\base-library\bella-canvas-3001\female-front-001\base.png'); print(i.shape if i is not None else 'OKUNAMADI')"
```

---

## 4 — Giysi maskesi

Kalibrasyonda `classic` çöktü (çalışan tolerance değeri yoktu). Gerçek
fotoğrafta fon kontrastı iyiyse çalışabilir — önce onu dene, ucuz.

```powershell
python tools\auto_mask.py bella-canvas-3001/female-front-001 --debug
```

**Kabul:** kaplama %25–60, uyarı yok.

Uyarı çıkarsa veya `_debug_mask.png` yanlışsa doğrudan `cloth`'a geç:

```powershell
python tools\auto_mask.py bella-canvas-3001/female-front-001 --method cloth --debug --force
```

`cloth` kalibrasyon asset'inde %42.7 kaplama, tişört %100, fon %0 verdi.
Bu yol artık doğrulanmış durumda.

**Gözle kontrol — `_debug_mask.png`:**

- Yaka çizgisi doğru mu, boyun teni maskeye girmiş mi
- Kollar maskede mi, koltuk altı temiz mi
- Etek çizgisi pantolonun üstünde mi kesiliyor
- Saç veya kolye sızmış mı

Yanlışsa GIMP'te rötuşla. Bu maske renk değiştirmenin sınırı; hatalıysa
siyah tişörtte tende siyah lekeler çıkar.

Kontrol bitince `_debug_mask.png` dosyasını sil.

---

## 5 — print_quad'ı ölç, tıklama

Bella Canvas 3001 ön baskı alanı **12 × 16 inç**. BC3001 M beden göğüs
genişliği **20 inç** (düz, tam). Bu ikisinden ölçek çıkar.

```powershell
python -c "import cv2,numpy as np; m=cv2.imread(r'assets\base-library\bella-canvas-3001\female-front-001\garment_mask.png',0)>127; ys,xs=np.where(m); print(f'giysi: x {xs.min()}-{xs.max()}  y {ys.min()}-{ys.max()}'); [print(f'  y={y}: govde {len(max(np.split(np.where(m[y])[0], np.where(np.diff(np.where(m[y])[0])>1)[0]+1), key=len))} px') for y in range(int(ys.min()+(ys.max()-ys.min())*0.35), int(ys.min()+(ys.max()-ys.min())*0.75), 100)]"
```

Kollar hizasının altındaki satırlarda **en geniş sürekli blok** gövde
genişliğidir. Sonra:

```
ppi        = govde_genisligi_px / 20
quad_w     = 12 * ppi
quad_h     = 16 * ppi
cx         = govde_merkezi_x
ust_y      = yaka_cukuru_y + 2.5 * ppi
print_quad = [[cx-quad_w/2, ust_y], [cx+quad_w/2, ust_y],
              [cx+quad_w/2, ust_y+quad_h], [cx-quad_w/2, ust_y+quad_h]]
```

**Yaka çukuru:** ön yakanın en alt noktası. Maskede yaka deliği
`fill_holes` tarafından kapatılmış olabilir — o durumda görselden gözle
oku.

```powershell
python tools\calibrate_quad.py bella-canvas-3001/female-front-001 --points X1,Y1 X2,Y2 X3,Y3 X4,Y4
```

Sıra: **sol-üst, sağ-üst, sağ-alt, sol-alt**

Bu adım, mockup'ı "güzel görünen" değil "doğru" yapan şeydir. Tasarım
gerçek baskı alanının gerçek oranında durur; "gelen ürün fotoğraftakinden
farklı" şikayetini kökten keser.

---

## 6 — Harita türetme · KARAR NOKTASI

```powershell
python tools\prepare_base.py bella-canvas-3001/female-front-001
```

**Kabul kriterleri:**

| Ölçüm | Kabul | İdeal | Kalibrasyonda |
|---|---|---|---|
| Giysi ort. parlaklık | 190–235 | — | 224.4 |
| **Kıvrım std** | **> 6** | **> 15** | 26.8 |
| Gölge aralığı | **> 50 seviye** | > 70 | 31 (dar) |
| Baskı alanı kaplama | %4–15 | — | %8.21 |

**Kıvrım std < 6 ise fotoğrafı yeniden çek.** Kod ayarıyla kurtarılmaz.
Işık düz demektir, displacement etkisiz kalır, motorun yarısı boşa gider.

Kıvrım/gürültü oranını da doğrula (kalibrasyonda 1.97):

```powershell
python -c "import cv2,numpy as np; D=r'assets\base-library\bella-canvas-3001\female-front-001'; d=cv2.imread(D+r'\displace.png',0).astype(np.float32); g=cv2.imread(D+r'\garment_mask.png',0)>127; s=cv2.GaussianBlur(d,(0,0),8); r=((s[g]-s[g].mean()).std())/max((d-s)[g].std(),1e-6); print(f'kivrim/gurultu {r:.2f}  ({\"kivrim baskin\" if r>1.5 else \"GURULTU BASKIN - yeniden cek\"})')"
```

---

## 7 — İlk render ve kalibrasyon

```powershell
python check_layout.py
python cli.py tasarimlar\test-design.png --model bella-canvas-3001/female-front-001
```

Kalibrasyon asset'inin değerlerini **başlangıç noktası olarak bile
kullanma** — gerçek fotoğrafın kıvrımı daha güçlü olacak. Sıfırdan tara:

```powershell
python cli.py tasarimlar\test-design.png --model bella-canvas-3001/female-front-001 --scale 0.9 --displace 10
python cli.py tasarimlar\test-design.png --model bella-canvas-3001/female-front-001 --scale 0.9 --displace 20
python cli.py tasarimlar\test-design.png --model bella-canvas-3001/female-front-001 --scale 0.9 --displace 30
```

| Belirti | Anahtar | Yön |
|---|---|---|
| Yapıştırılmış duruyor | `--displace` yükselt | 10 → 40 |
| Baskı dalgalı, bozuk | `--displace` düşür | |
| Gölge yetersiz | `--shading` yükselt | → 1.0 |
| Baskı fazla karanlık | `--shading` düşür | → 0.5 |

`--scale`'e **dokunma.** Adım 5'te gerçek baskı alanından türetildi;
değiştirmek mockup'ı yanlış yapar. Tasarım küçük görünüyorsa sebep
tasarımın kendi kenar boşluğudur, ölçek değil.

Beğenilen değerleri `meta.json`'a kalıcı yaz.

---

## 8 — Renk doğrulaması

```powershell
python tools\verify_recolor.py bella-canvas-3001/female-front-001 --write
```

Kalibrasyon asset'inde beş renk de geçti (`black` 0.82, `navy` 0.86).
Gerçek fotoğrafın L\* yayılımı daha geniş olacağı için sonuç en az bu
kadar iyi olmalı.

**Çıkış kodu 2 gelirse:** siyah ve/veya lacivert için ayrı koyu base
gerekiyor — ikinci bir tişört (siyah BC3001) fotoğraflanmalı.

---

## 9 — Tam doğrulama

Kalibrasyon asset'inde 34 kontrolün tamamı geçti. Aynılarını burada da
doğrula:

| # | Kontrol | Kabul |
|---|---|---|
| 1 | `garment_mask` boyutu = `base` | eşit |
| 2 | `garment_mask` ikili (0/255) | evet |
| 3 | `garment_mask` kaplama | %25–60 |
| 4 | `print_mask` giysi dışına taşan | **0 piksel** |
| 5 | `print_mask` alan | %4–15 |
| 6 | `displace` giysi dışı | **tam 128, std 0** |
| 7 | `displace` kıvrım std | **> 6** |
| 8 | `displace` kıvrım/gürültü | **> 1.5** |
| 9 | `shading` giysi dışı | **tam 128** |
| 10 | `shading` giysi ortalaması | 128 ± 3 |
| 11 | `shading` aralık | **> 50 seviye** |
| 12 | `meta.json` quad giysi içinde | evet |
| 13 | Render: baskı alanı dışında değişim | **0 piksel** |
| 14 | Render: tasarım kontrastı | std > 30 |

Kritik olanlar 4, 6, 9 ve 13. Bunlar sıfır tolerans; hepsi maskeleme
doğruluğunu ölçüyor ve biri bile sapıyorsa çıktı bozuktur.

---

## 10 — publishable=true

**Yalnızca Adım 9'un tamamı geçtikten sonra.**

```jsonc
{
  "source": "photographed",
  "source_detail": "kendi çekimim, 2026-08-XX, <yer>, model onayı alındı",
  "verified_garment": true,      // elindeki gerçekten BC3001
  "publishable": true,           // Etsy'ye çıkabilir
  "created": "2026-08-XX"
}
```

`verified_garment: true` yalnızca elindeki tişört gerçekten Bella Canvas
3001 ise. Başka marka bir tişört fotoğrafladıysan `false` bırak ve
`publishable`'ı da `false` yap — sattığın ürün BC3001 olduğu için
fotoğraftaki de o olmalı.

---

## 11 — Üretim

```powershell
python batch.py --designs tasarimlar --models bella-canvas-3001/female-front-001 --colors all
python tools\export_etsy.py outputs\batch\<zaman-damgasi> --shape square
```

`BÜYÜTÜLDÜ` uyarısı çıkmamalı. Çıkıyorsa base fotoğraf 2000 pikselin
altında ve bu noktada düzeltilemez.

---

## Karar noktaları özeti

Üç yerde durup karar verilir. Gerisi mekanik.

| Adım | Karar | Yanlışsa |
|---|---|---|
| 4 | Maske doğru mu? | Renk değiştirmede tende leke |
| 6 | Kıvrım std > 6 mı? | **Fotoğrafı yeniden çek** |
| 8 | Siyah eşiği geçti mi? | İkinci (koyu) tişört gerekir |

En pahalısı Adım 6. Çekimi o sayıyı düşünerek yap: yan ışık, gölge,
kıvrım.
