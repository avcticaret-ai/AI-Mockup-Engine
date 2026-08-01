# ADR-0003 — Flatlay Asset Pipeline

Status: Accepted
Sprint: 9
Date: 2026-08-01

---

# Amaç

AI Mockup Engine yalnızca insan üzerindeki ürün fotoğraflarını değil,
üstten çekilmiş (Flatlay) ürün görsellerini de aynı asset pipeline içinde
desteklemelidir.

Bu destek mevcut Human Pipeline davranışını DEĞİŞTİRMEYECEK,
yalnızca yeni bir asset tipi ekleyecektir.

Backward compatibility zorunludur.

---

# Desteklenecek Asset Tipleri

## Human

Örnek

bella-canvas-3001/female-front-005

Pipeline

ingest
↓

auto_mask(classic)
↓

derive_quad(human)
↓

prepare_base
↓

verify_asset

---

## Flatlay

Örnek

bella-canvas-3001/flatlay-001

Pipeline

ingest
↓

auto_mask(flatlay)
↓

derive_quad(flatlay)
↓

prepare_base
↓

verify_asset

---

# Asset Type

meta.json içerisine yeni alan eklenir.

```json
{
    "asset_type": "human"
}
```

veya

```json
{
    "asset_type": "flatlay"
}
```

Varsayılan:

```
human
```

Eski asset'ler etkilenmeyecektir.

---

# Auto Detection

build_asset.py aşağıdaki sırayla deneyecektir.

Human

classic

↓

cloth

↓

başarılıysa devam

Flatlay

classic başarısız

↓

cloth başarısız

↓

flatlay yöntemi

↓

başarılıysa devam

↓

değilse hata

---

# Flatlay Masking

HSV yöntemi yeterli değildir.

Sebep

• açık renk kumaş
• açık renk arka plan
• gölgeler

Renk farkı çoğu zaman 2–5 L* seviyesindedir.

Bu nedenle yalnızca HSV kullanılamaz.

---

# Kullanılacak Algoritma

1.

Bilateral Filter

Amaç

kumaş dokusunu bastırmak

kenarı korumak

---

2.

Lab Color Space

RGB kullanılmayacak.

Karşılaştırmalar Lab uzayında yapılacaktır.

---

3.

Center Seed

Görsel merkezi

80×80

bölgesi örneklenir.

Median Lab

referans renk olur.

---

4.

First Pass

Dar ΔE eşiği

yaklaşık

ΔE < 6

Güvenilir çekirdek oluşturur.

---

5.

Largest Component

En büyük bileşen korunur.

---

6.

Second Pass

Referans

ilk maskenin istatistiğinden tekrar hesaplanır.

Bu sayede

• gölgeler

• kol kıvrımları

• etek kıvrımları

maskeye dahil edilir.

---

7.

Morphology

Open

↓

Close

↓

Hole Fill

↓

Largest Component

---

# Edge Constraint

Kenar bilgisi

maskeyi üretmek için değil,

taşmayı durdurmak için kullanılacaktır.

Sobel / Gradient

yalnızca sınır görevi görür.

---

# derive_quad()

Human algoritması değişmeyecektir.

Flatlay için yeni dal eklenecektir.

---

Human

Spec ölçüsü

20"

↓

px/in

↓

quad

---

Flatlay

Spec ölçüsü kullanılmayacaktır.

Quad doğrudan gövde oranından hesaplanacaktır.

---

# Flatlay Quad

Gövde genişliği

↓

%60

↓

print width

Print oranı

12 × 16

korunacaktır.

Örnek

Body width

800 px

↓

Quad width

480 px

↓

Quad height

640 px

---

meta.json

```json
{
    "quad_source":"auto-flatlay"
}
```

---

# prepare_base()

Davranış değişmeyecek.

Mevcut

displace

shading

print_mask

üretimi aynen kullanılacaktır.

---

# verify_asset()

Davranış değişmeyecek.

Mevcut kontroller

• mask

• quad

• render

• shading

• displacement

aynı kalacaktır.

Flatlay için özel kontrol eklenmeyecektir.

---

# UI Etkisi

Studio ileride asset tipini otomatik gösterecektir.

Örnek

Asset Type

○ Human

○ Flatlay

Operatör isterse değiştirebilir.

---

# Backward Compatibility

Human Pipeline

davranışı

değiştirilmeyecektir.

Aşağıdaki dosyaların render davranışı
bit düzeyinde aynı kalmalıdır.

female-front-001

female-front-005

male-front-001

---

# Değişecek Dosyalar

tools/auto_mask.py

↓

flatlay yöntemi

tools/derive_quad.py

↓

flatlay dalı

tools/build_asset.py

↓

asset_type yönetimi

↓

auto zinciri

---

# Değişmeyecek Dosyalar

prepare_base.py

verify_asset.py

engine/

cli.py

batch.py

renderer.py

pipeline.py

---

# Başarı Kriterleri

Flatlay görseli

↓

tek komut

↓

asset oluşmalı

↓

verify_asset PASS

↓

CLI render PASS

↓

Human asset'lerde davranış değişmemeli

---

# Sprint Sonu Hedefi

AI Mockup Engine artık yalnızca insan üzerindeki ürünleri değil,
Flatlay ürün görsellerini de aynı mimari altında destekleyen
çoklu asset pipeline yapısına sahip olacaktır.