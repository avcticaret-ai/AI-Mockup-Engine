Hedef

Flatlay desteğini eklemek değil.

Asset Pipeline'ı ürün tiplerinden bağımsız hale getirmek.

Yeni mimari
assets/
└── base-library/
    └── bella-canvas-3001/
        ├── human/
        │   ├── female-front-001/
        │   ├── female-front-005/
        │   └── male-front-001/
        │
        └── flatlay/
            ├── flatlay-001/
            └── flatlay-002/

veya bununla aynı mantıkta başka temiz bir yapı önerilebilir.

asset_type

Yeni kavram:

human
flatlay

Şimdilik sadece bunlar.

İleride

hoodie
sweatshirt
tank-top
tote-bag
mug
poster
canvas
phone-case

eklenecek.

build_asset.py

Desteklesin:

--asset-type human
--asset-type flatlay

Verilmezse otomatik tahmin etmeye çalışsın.

auto_mask.py

Human koduna dokunma.

Yeni branch:

flatlay

Lab seed growing

edge constraint

iki geçişli büyüme

derive_quad.py

Human algoritması tamamen aynı kalsın.

Flatlay için ayrı branch.

Spec ölçülerini kullanma.

Quad

=

gövde genişliğinin %60'ı

merkez hizalı.

meta.json

asset_type
quad_source

alanlarını yaz.

verify_asset.py

Davranışı değişmeyecek.

Asset type ne olursa olsun aynı doğrulamaları kullanacak.

Render Engine

Hiç değişmeyecek.

CLI

Hiç değişmeyecek.

API

Hiç değişmeyecek.

Compositor

Hiç değişmeyecek.

Önemli

Bu sprintte amaç sadece flatlay çalıştırmak değildir.

Amaç;

Asset Pipeline'ı çok ürünlü SaaS mimarisine hazırlamaktır.

Human ile Flatlay iki bağımsız pipeline olacak.

Render Engine ise ortak kalacaktır.

Backward compatibility %100 korunmalıdır.

Human modellerinde tek piksel bile değişiklik oluşmamalıdır.