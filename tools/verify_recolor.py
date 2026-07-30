#!/usr/bin/env python3
"""Recolor kalitesini CIELAB L* yayılımı ile ölçer.

    python tools/verify_recolor.py test-model
    python tools/verify_recolor.py bella-canvas-3001/pose-01-front --write

Neden L*
--------
Kıvrımların görünürlüğü algısal bir niteliktir. sRGB seviye sayısı
yanıltıcı: gamma yüzünden koyu bölgede 10 seviye, açık bölgede 10
seviyeden çok daha fazla algısal fark demek. CIELAB L* algısal olarak
düzgün olduğu için koyu ve açık rengi aynı ölçekte karşılaştırmaya izin
veriyor.

KARAR ÖLÇÜTÜ
------------
Bir rengin L* yayılımı, beyaz base'in yayılımının %60'ının altına
düşerse kıvrımlar düz okunur -> o renk için ayrı koyu base gerekir.

Araç iki yöntemi yan yana ölçüyor:
  lab       CIELAB kontrast koruma (üretimde kullanılan)
  multiply  linear uzayda çarpma (naif, karşılaştırma için)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from mockup_engine import load_model  # noqa: E402
from mockup_engine.recolor import (  # noqa: E402
    COLOR_PRESETS, lightness_spread, recolor_garment,
)

ENGINE = Path(__file__).resolve().parent.parent
LIBRARY = ENGINE / "assets" / "base-library"

THRESHOLD_RATIO = 0.60  # beyaz base yayılımının bu oranı altı = yetersiz


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("model_id", help="ör. test-model")
    p.add_argument("--library", default=str(LIBRARY))
    p.add_argument("--colors", help="virgülle ayrılmış; varsayılan tüm presetler")
    p.add_argument("--write", action="store_true",
                   help="renkli base'leri outputs/recolor/ altına yaz")
    args = p.parse_args()

    model = load_model(args.model_id, Path(args.library))
    base = model.base.astype(np.float32) / 255.0
    mask = model.garment_mask

    colors = ([c.strip() for c in args.colors.split(",")]
              if args.colors else list(COLOR_PRESETS))

    # Referans: dokunulmamış base
    ref = lightness_spread(base, mask)
    threshold = ref["L_span"] * THRESHOLD_RATIO

    w, h = model.size
    print(f"\nModel      : {args.model_id}  ({w}x{h})")
    print(f"Giysi alanı: {(mask > 127).sum():,} piksel")
    print(f"\nBASE (dokunulmamış)")
    print(f"  L* ortalama {ref['L_mean']:6.2f}   yayılım (p5-p95) {ref['L_span']:6.2f}"
          f"   std {ref['L_std']:5.2f}")
    print(f"\nEşik: yayılım < {threshold:.2f} ise kıvrımlar düz okunur"
          f"  (base'in %{THRESHOLD_RATIO*100:.0f}'ı)")

    out_dir = ENGINE / "outputs" / "recolor"
    if args.write:
        out_dir.mkdir(parents=True, exist_ok=True)

    header = (f"\n{'renk':<14}{'yöntem':<10}{'L* ort':>8}{'yayılım':>9}"
              f"{'oran':>7}{'alt':>6}{'üst':>6}   sonuç")
    print(header)
    print("-" * len(header.strip()) )

    verdicts: dict[str, bool] = {}

    for color in colors:
        for method in ("lab", "multiply"):
            try:
                recolored, stats = recolor_garment(
                    base, mask, color, method=method)
            except ValueError as err:
                print(f"{color:<14}{method:<10}  HATA: {err}")
                continue

            m = lightness_spread(recolored, mask)
            ratio = m["L_span"] / ref["L_span"] if ref["L_span"] else 0.0
            passed = m["L_span"] >= threshold

            mark = "GEÇTI" if passed else "YETERSIZ"
            print(f"{color:<14}{method:<10}{m['L_mean']:8.2f}{m['L_span']:9.2f}"
                  f"{ratio:7.2f}{stats['clip_low']:5.1f}%{stats['clip_high']:5.1f}%   {mark}")

            if method == "lab":
                verdicts[color] = passed

            if args.write:
                name = f"{args.model_id.replace('/', '_')}-{color}-{method}.png"
                cv2.imwrite(str(out_dir / name),
                            (recolored * 255).astype(np.uint8))
        print()

    # -- sonuç ------------------------------------------------------------
    failed = [c for c, ok in verdicts.items() if not ok]

    print("=" * 62)
    if failed:
        print(f"\nTEK BASE AİLESİ YETERSİZ.")
        print(f"Şu renkler için ayrı koyu base gerekiyor: {', '.join(failed)}\n")
        print("Sıradaki adım: aynı poz için koyu base asset üret")
        print("  (siyah veya lacivert tişört giyen model),")
        print("  ardından bu renkleri o base'den türet.\n")
        return 2

    print(f"\nTEK BASE AİLESİ YETERLİ.")
    print("Beş renk de eşiği geçti; ayrı koyu base gerekmiyor.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
