#!/usr/bin/env python3
"""base.png + garment_mask.png + print_quad  ->  print_mask / displace / shading

Gerçek bir fotoğraftan üç haritayı türetir. Elle yapılması gereken tek iş
garment_mask.png ve print_quad; gerisi buradan çıkar.

    python tools/prepare_base.py bella-canvas-3001/female-front-001

Türetme mantığı
---------------
displace : luminance'ın YÜKSEK geçiren bileşeni. Genel aydınlatmayı
           (çok kaba) ve kumaş dokusunu (çok ince) atıp yalnızca orta
           frekanslı kıvrım yapısını bırakır.

shading  : luminance'ın ALÇAK geçiren bileşeni. Nötr nokta sabit 128
           DEĞİL, giysinin kendi ortalama parlaklığıdır. Beyaz tişörtün
           ortalaması ~210 civarındadır; bunu 128 kabul edersen tüm
           tasarım sistematik olarak aydınlanır. Faz 0'da compositor
           tarafında yakalanan nötr nokta hatasının varlık üretimi
           tarafındaki karşılığı bu.

print_mask : quad ∩ garment_mask, kenarları içeri çekilip yumuşatılmış.
             İçeri çekme, baskının tişört kenarından taşmasını önler.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ENGINE = Path(__file__).resolve().parent.parent
LIBRARY = ENGINE / "assets" / "base-library"


def luminance(bgr: np.ndarray) -> np.ndarray:
    """Algısal parlaklık. Basit ortalama yerine BT.601 ağırlıkları --
    kumaş gölgesinin gerçek koyuluğunu daha doğru veriyor."""
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0


def sigma_for(image_h: int, fraction: float) -> float:
    """Blur yarıçapını görsel yüksekliğinin oranı olarak verir.

    Sabit piksel değeri kullanılırsa 1400px'lik test görselinde doğru
    ayarlanan değer 4000px'lik gerçek fotoğrafta çok zayıf kalır.
    """
    return max(1.0, image_h * fraction)


def build_displace(
    lum: np.ndarray, garment: np.ndarray, detail: float, structure: float
) -> np.ndarray:
    """Yüksek geçiren filtre -> kıvrım yapısı."""
    h = lum.shape[0]

    # İnce dokuyu at (kumaş gözenekleri displacement'a girmemeli)
    fine = cv2.GaussianBlur(lum, (0, 0), sigma_for(h, detail))
    # Genel aydınlatmayı at
    coarse = cv2.GaussianBlur(lum, (0, 0), sigma_for(h, structure))

    folds = fine - coarse

    m = garment.astype(np.float32) / 255.0
    inside = folds[garment > 127]
    if inside.size == 0:
        raise SystemExit("garment_mask.png boş görünüyor -- maskeyi kontrol et.")

    # Giysi içindeki gerçek aralığa göre normalize et, sonra 128'e ortala.
    scale = float(np.percentile(np.abs(inside), 99)) or 1e-6
    normalized = np.clip(folds / scale, -1.0, 1.0)

    out = 128.0 + normalized * 127.0
    out = out * m + 128.0 * (1.0 - m)  # giysi dışı nötr
    return np.clip(out, 0, 255).astype(np.uint8)


def build_shading(
    lum: np.ndarray, garment: np.ndarray, structure: float, gain: float
) -> tuple[np.ndarray, float]:
    """Alçak geçiren filtre -> ışık/gölge. Nötr = giysinin ortalaması."""
    h = lum.shape[0]
    low = cv2.GaussianBlur(lum, (0, 0), sigma_for(h, structure))

    garment_mean = float(low[garment > 127].mean())

    out = 128.0 + (low - garment_mean) * 255.0 * gain
    m = garment.astype(np.float32) / 255.0
    out = out * m + 128.0 * (1.0 - m)
    return np.clip(out, 0, 255).astype(np.uint8), garment_mean


def build_print_mask(
    quad: np.ndarray, garment: np.ndarray, inset: float, feather: float
) -> np.ndarray:
    """quad ∩ garment, içeri çekilmiş ve yumuşatılmış."""
    h, w = garment.shape[:2]

    area = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(area, [quad.astype(np.int32)], 255)

    mask = cv2.bitwise_and(area, np.where(garment > 127, 255, 0).astype(np.uint8))

    # Tişört kenarından taşmayı önlemek için içeri çek
    inset_px = int(round(sigma_for(h, inset)))
    if inset_px > 0:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (inset_px * 2 + 1, inset_px * 2 + 1)
        )
        mask = cv2.erode(mask, kernel)

    feather_px = sigma_for(h, feather)
    return cv2.GaussianBlur(mask, (0, 0), feather_px)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("model_id", help="ör. bella-canvas-3001/female-front-001")
    p.add_argument("--library", default=str(LIBRARY))
    p.add_argument("--detail", type=float, default=0.0015,
                   help="ince doku eşiği (yükseklik oranı)")
    p.add_argument("--structure", type=float, default=0.020,
                   help="kıvrım/ışık ayrım eşiği (yükseklik oranı)")
    p.add_argument("--shading-gain", type=float, default=1.0,
                   help="gölge kontrastı çarpanı")
    p.add_argument("--inset", type=float, default=0.004,
                   help="baskı maskesi içeri çekme")
    p.add_argument("--feather", type=float, default=0.004,
                   help="baskı maskesi kenar yumuşatma")
    p.add_argument("--force", action="store_true",
                   help="mevcut haritaların üzerine yaz")
    args = p.parse_args()

    model_dir = Path(args.library) / args.model_id
    if not model_dir.is_dir():
        print(f"HATA: klasör yok: {model_dir}", file=sys.stderr)
        return 1

    for required in ("base.png", "garment_mask.png", "meta.json"):
        if not (model_dir / required).exists():
            print(f"HATA: {required} eksik. "
                  f"{'Önce calibrate_quad.py çalıştır.' if required == 'meta.json' else ''}",
                  file=sys.stderr)
            return 1

    base = cv2.imread(str(model_dir / "base.png"), cv2.IMREAD_COLOR)
    garment = cv2.imread(str(model_dir / "garment_mask.png"), cv2.IMREAD_GRAYSCALE)
    meta = json.loads((model_dir / "meta.json").read_text(encoding="utf-8"))

    if base.shape[:2] != garment.shape[:2]:
        print(f"HATA: garment_mask boyutu base.png ile uyuşmuyor "
              f"({garment.shape[1]}x{garment.shape[0]} vs "
              f"{base.shape[1]}x{base.shape[0]})", file=sys.stderr)
        return 1

    quad = meta.get("print_quad")
    if not quad or len(quad) != 4:
        print("HATA: meta.json içinde 4 noktalı print_quad yok. "
              "Önce calibrate_quad.py çalıştır.", file=sys.stderr)
        return 1

    existing = [f for f in ("print_mask.png", "displace.png", "shading.png")
                if (model_dir / f).exists()]
    if existing and not args.force:
        print(f"Zaten var: {', '.join(existing)}. Üzerine yazmak için --force.")
        return 1

    lum = luminance(base)

    displace = build_displace(lum, garment, args.detail, args.structure)
    shading, garment_mean = build_shading(lum, garment, args.structure,
                                          args.shading_gain)
    print_mask = build_print_mask(np.array(quad, dtype=np.float32), garment,
                                  args.inset, args.feather)

    cv2.imwrite(str(model_dir / "displace.png"), displace)
    cv2.imwrite(str(model_dir / "shading.png"), shading)
    cv2.imwrite(str(model_dir / "print_mask.png"), print_mask)

    h, w = base.shape[:2]
    coverage = float((print_mask > 8).sum()) / (h * w) * 100

    print(f"\n{args.model_id}  ({w}x{h})")
    print(f"  giysi ortalama parlaklık : {garment_mean * 255:.1f}  -> 128 nötr kabul edildi")
    print(f"  kıvrım aralığı (std)     : {displace[garment > 127].std():.1f}")
    print(f"  gölge aralığı            : {shading[garment > 127].min()} - "
          f"{shading[garment > 127].max()}")
    print(f"  baskı alanı kaplama      : %{coverage:.2f} of frame")
    print(f"\n  displace.png, shading.png, print_mask.png yazıldı\n")

    if displace[garment > 127].std() < 6:
        print("  UYARI: kıvrım aralığı çok düşük. Fotoğrafta ışık muhtemelen")
        print("  fazla düz -- displacement neredeyse etkisiz kalacak.\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
