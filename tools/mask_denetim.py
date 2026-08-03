#!/usr/bin/env python3
"""Kütüphanedeki tüm asset'lerin giysi maskesini denetler.

    python tools/mask_denetim.py
    python tools/mask_denetim.py --recolor        # renk testi de yap

Renk değiştirme YALNIZCA garment_mask.png içindeki pikselleri boyar.
Maske bir kolu veya eteği kaçırıyorsa o bölge orijinal renkte kalır --
ve bu ancak renkli render alındıktan sonra fark edilir.

Bu araç maskeyi önceden denetler:

  kaplama       %15-70 dışı  -> maske çok küçük veya çok büyük
  simetri       >%12 fark    -> bir kol eksik olabilir
  kadraj kenarı geniş temas  -> komşu obje sızmış olabilir
  parça sayısı  >1           -> kopuk bölge var

--recolor ile ayrıca gerçek bir renk değişimi yapıp maske dışında
kalan giysi benzeri piksel olup olmadığını ölçer.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from mockup_engine import list_models, load_model  # noqa: E402
from mockup_engine.recolor import recolor_garment  # noqa: E402

ENGINE = Path(__file__).resolve().parent.parent
LIBRARY = ENGINE / "assets" / "base-library"

COVERAGE_MIN, COVERAGE_MAX = 15.0, 70.0
SYMMETRY_WARN = 12.0


def denetle(model_id: str, library: Path, recolor_test: bool) -> list[str]:
    """Bir asset'i denetler, sorun listesi döndürür."""
    sorunlar: list[str] = []

    try:
        model = load_model(model_id, library)
    except Exception as err:
        return [f"yuklenemedi: {err}"]

    m = model.garment_mask > 127
    h, w = m.shape[:2]

    cov = 100.0 * m.mean()
    if not (COVERAGE_MIN < cov < COVERAGE_MAX):
        sorunlar.append(f"kaplama %{cov:.1f} (beklenen %{COVERAGE_MIN:.0f}-{COVERAGE_MAX:.0f})")

    n, _ = cv2.connectedComponents(m.astype(np.uint8))
    if n - 1 > 1:
        sorunlar.append(f"{n-1} ayri parca (tek olmali)")

    ys, xs = np.where(m)
    if len(xs) == 0:
        return ["maske bos"]

    cx = (int(xs.min()) + int(xs.max())) // 2
    sol = int(m[:, :cx].sum())
    sag = int(m[:, cx:].sum())
    asim = abs(sol - sag) / max(sol, sag, 1) * 100
    if asim > SYMMETRY_WARN:
        yon = "sag" if sag < sol else "sol"
        sorunlar.append(f"simetri %{asim:.0f} fark -- {yon} kol eksik olabilir")

    edge = int(m[0].sum() + m[-1].sum() + m[:, 0].sum() + m[:, -1].sum())
    if edge > int(0.02 * (2 * w + 2 * h)):
        sorunlar.append(f"kadraj kenarina {edge} px temas -- komsu obje sizmis olabilir")

    if recolor_test:
        base = model.base.astype(np.float32) / 255.0
        try:
            out, _ = recolor_garment(base, model.garment_mask, "navy")
        except Exception as err:
            sorunlar.append(f"recolor hatasi: {err}")
            return sorunlar

        out8 = (out * 255).astype(np.uint8)
        degisim = np.abs(out8.astype(np.int16) - model.base.astype(np.int16)).max(axis=2)

        # Recolor kenari YUMUSATIYOR (edge_feather), yani maskenin birkac
        # piksel disina tasmasi NORMAL. Ilk surumde bu yanlis pozitif
        # veriyordu: saglam assetlerde bile "maske disinda 13.882 px
        # degisti" diyordu. Maskeyi feather kadar genisletip onun
        # disini kontrol ediyoruz.
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))
        genis = cv2.dilate(m.astype(np.uint8), k) > 0
        disari = int((degisim > 8)[~genis].sum())
        if disari > w * h * 0.002:
            sorunlar.append(f"maske disinda {disari:,} px degisti "
                            f"-- maske yanlis bolgeyi kapsiyor olabilir")

        # Maske icinde degismeyen buyuk bolge = maske dogru ama recolor
        # etkisiz (koyu renk uzerine koyu renk gibi)
        icerde_sabit = int((degisim < 3)[m].sum())
        if icerde_sabit > m.sum() * 0.2:
            sorunlar.append(f"maske icinde %{100*icerde_sabit/m.sum():.0f} degismedi")

    return sorunlar


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--library", default=str(LIBRARY))
    p.add_argument("--recolor", action="store_true",
                   help="gercek renk degisimi yapip olc (yavas)")
    p.add_argument("--only", help="tek model")
    args = p.parse_args()

    lib = Path(args.library)
    models = [args.only] if args.only else list_models(lib)
    if not models:
        print(f"Kutuphane bos: {lib}", file=sys.stderr)
        return 1

    print(f"\n{len(models)} asset denetleniyor"
          f"{' (renk testi dahil)' if args.recolor else ''}\n")

    sorunlu = 0
    for mid in models:
        sorunlar = denetle(mid, lib, args.recolor)
        if sorunlar:
            sorunlu += 1
            print(f"  [SORUN] {mid}")
            for s in sorunlar:
                print(f"          - {s}")
        else:
            print(f"  [tamam] {mid}")

    print()
    if sorunlu:
        print(f"{sorunlu}/{len(models)} asset'te sorun var.\n")
        print("Maske eksikse:")
        print("  1. python tools/auto_mask.py <model> --debug --force")
        print("     _debug_mask.png'ye bak, eksik bolgeyi gor")
        print("  2. Esikleri gevset: --s-max 60 --v-min 90")
        print("     veya baska yontem dene: --method cloth")
        print("  3. Duzelmiyorsa GIMP'te elle rotusla")
        print("  4. python tools/prepare_base.py <model> --force")
        return 1

    print("Tum assetler saglam.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
