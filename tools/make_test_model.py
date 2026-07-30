#!/usr/bin/env python3
"""test-model base model varlıklarını üretir.

Bu SENTETİK bir base model -- gerçek fotoğraf değil. Amacı, motoru
gerçek varlık üretmeden önce uçtan uca doğrulayabilmek. Kumaş kıvrımları
prosedürel olarak üretiliyor, bu yüzden displacement ve shading
haritaları da matematiksel olarak tutarlı.

Gerçek base modele geçerken bu dosya çöpe gider; yerini prepare_base.py
alır (fotoğraftan segmentasyonla harita türetme).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

W, H = 1400, 1800
OUT = Path(__file__).resolve().parent.parent / "assets" / "base-library" / "test-model"


def shirt_polygon() -> np.ndarray:
    """Önden görünen bir tişörtün dış hatları."""
    return np.array([
        [430, 300],   # sol omuz üstü
        [560, 250],   # sol yaka
        [700, 300],   # yaka ortası
        [840, 250],   # sağ yaka
        [970, 300],   # sağ omuz üstü
        [1160, 430],  # sağ kol dış
        [1090, 640],  # sağ kol alt
        [1000, 570],  # sağ koltuk altı
        [1030, 1500], # sağ etek
        [370, 1500],  # sol etek
        [400, 570],   # sol koltuk altı
        [310, 640],   # sol kol alt
        [240, 430],   # sol kol dış
    ], dtype=np.int32)


def fold_field(mask: np.ndarray) -> np.ndarray:
    """Kumaş kıvrım alanı: birkaç dikey kırışık + yumuşak gürültü.

    Gerçek kumaşta kıvrımlar dikey baskındır (yerçekimi) ve koltuk
    altından çapraz çıkar. Bunu birkaç sinüsün toplamıyla taklit ediyoruz.
    """
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)

    field = np.zeros((H, W), dtype=np.float32)
    # Dikey ana kırışıklar
    field += 0.45 * np.sin(x / 58.0 + np.sin(y / 240.0) * 2.2)
    field += 0.28 * np.sin(x / 121.0 - y / 430.0)
    # Koltuk altından gelen çapraz gerilme
    field += 0.22 * np.sin((x * 0.6 + y * 0.9) / 150.0)
    # Göğüs bölgesinde hafif şişkinlik (gövde hacmi)
    bulge = np.exp(-(((x - 700) ** 2) / (2 * 320.0 ** 2) +
                     ((y - 760) ** 2) / (2 * 380.0 ** 2)))
    field += 0.55 * bulge

    # Yumuşak rastgele doku
    rng = np.random.default_rng(7)
    noise = rng.random((H // 20, W // 20)).astype(np.float32)
    noise = cv2.resize(noise, (W, H), interpolation=cv2.INTER_CUBIC)
    field += 0.18 * (cv2.GaussianBlur(noise, (0, 0), 12) - 0.5) * 2

    field = cv2.GaussianBlur(field, (0, 0), 6)

    # Yalnızca giysi bölgesinde anlamlı; dışarısı nötr kalsın
    m = mask.astype(np.float32) / 255.0
    field = field * m

    lo, hi = field.min(), field.max()
    return (field - lo) / max(hi - lo, 1e-6)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # --- giysi maskesi ---
    garment = np.zeros((H, W), dtype=np.uint8)
    cv2.fillPoly(garment, [shirt_polygon()], 255)
    # yaka oyuntusu
    cv2.ellipse(garment, (700, 292), (108, 58), 0, 0, 360, 0, -1)
    garment = cv2.GaussianBlur(garment, (0, 0), 2)
    garment = np.where(garment > 127, 255, 0).astype(np.uint8)

    folds = fold_field(garment)

    # --- base görsel ---
    # stüdyo arka planı: hafif dikey gradyan + vinyet
    grad = np.linspace(232, 208, H, dtype=np.float32)[:, None].repeat(W, axis=1)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    vignette = 1.0 - 0.16 * (((xx - W / 2) / (W / 2)) ** 2 +
                             ((yy - H / 2) / (H / 2)) ** 2)
    background = grad * vignette

    # tişört: beyaz kumaş, kıvrımlara göre aydınlık/karanlık
    shirt = 214.0 + (folds - 0.5) * 86.0
    m = garment.astype(np.float32) / 255.0
    plate = background * (1 - m) + shirt * m

    # giysi kenarına ince gölge -- silueti arka plandan ayırır
    edge = cv2.GaussianBlur(m, (0, 0), 9) - m
    plate -= np.clip(edge, 0, 1) * 55.0

    base = np.clip(plate, 0, 255).astype(np.uint8)
    base = cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)

    # --- baskı alanı maskesi ---
    print_mask = np.zeros((H, W), dtype=np.uint8)
    cv2.rectangle(print_mask, (472, 470), (928, 1080), 255, -1)
    print_mask = cv2.bitwise_and(print_mask, garment)
    print_mask = cv2.GaussianBlur(print_mask, (0, 0), 6)

    # --- displacement haritası ---
    displace = np.clip(folds * 255.0, 0, 255).astype(np.uint8)

    # --- gölge haritası ---
    # 128 = nötr. Kıvrımların düşük frekanslı bileşeni ışığı taşır.
    low = cv2.GaussianBlur(folds, (0, 0), 26)
    shading = np.clip(128 + (low - 0.5) * 150.0, 0, 255).astype(np.uint8)
    shading[garment == 0] = 128  # giysi dışı nötr

    cv2.imwrite(str(OUT / "base.png"), base)
    cv2.imwrite(str(OUT / "garment_mask.png"), garment)
    cv2.imwrite(str(OUT / "print_mask.png"), print_mask)
    cv2.imwrite(str(OUT / "displace.png"), displace)
    cv2.imwrite(str(OUT / "shading.png"), shading)

    print(f"test-model varlıkları yazıldı -> {OUT}")


if __name__ == "__main__":
    main()
