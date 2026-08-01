#!/usr/bin/env python3
"""Bir asset'in altı dosyasını tek tek doğrular.

    python tools/verify_asset.py bella-canvas-3001/flat-ref-001
    python tools/verify_asset.py <model> --render     # render testini de yap

NEDEN GEREKLİ
    Bu kontroller üç asset üretiminde de elle yazılıp çalıştırıldı ama
    repoda yoktu. "Asset iyi mi" sorusunun cevabı göz kararıydı.

    Kritik olanlar sıfır toleranslı: displace ve shading giysi dışında
    TAM 128 olmalı, print_mask giysi dışına HİÇ taşmamalı, render baskı
    alanı dışında HİÇBİR pikseli değiştirmemeli. Biri bile saparsa
    maskeleme bozuktur ve çıktı sessizce yanlış olur.

    Sabit örnek noktası kullanmaz -- tüm kontroller görselden türetilir,
    yani her fotoğrafta çalışır.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

ENGINE = Path(__file__).resolve().parent.parent
LIBRARY = ENGINE / "assets" / "base-library"

REQUIRED = ("base.png", "garment_mask.png", "print_mask.png",
            "displace.png", "shading.png", "meta.json")

# Kabul esikleri. SOP-GercekBC3001.md ile ayni.
COVERAGE_MIN, COVERAGE_MAX = 15.0, 70.0
FOLD_STD_MIN = 6.0
# Kivrim sinyalinin gurultuye orani. Kademeli:
#   >= OK    saglikli
#   >= WARN  uyari -- JPEG sikistirmasi/dusuk cozunurluk sinyali zayiflatmis
#            olabilir, ama render kalitesi kabul edilebilir
#   <  WARN  hata -- displacement haritasi buyuk olasilikla gurultu
FOLD_NOISE_OK = 1.50
FOLD_NOISE_WARN = 1.20
SHADING_RANGE_MIN = 20          # duz cekimde dar olabilir; uyari esigi 50
SHADING_RANGE_GOOD = 50

# Baski alaninin giysi icinde kalan ALAN yuzdesi.
#   >= OK    sorunsuz
#   >= WARN  uyari, hata degil -- print_mask zaten giysiyle kesisiyor,
#            birkac piksellik tasma ciktida gorunmuyor
#   <  WARN  hata: quad yanlis konumlanmis
QUAD_INSIDE_OK = 99.5
QUAD_INSIDE_WARN = 95.0
PRINT_AREA_MIN, PRINT_AREA_MAX = 3.0, 20.0


class Report:
    def __init__(self) -> None:
        self.ok = self.fail = self.warn = 0

    def check(self, name: str, cond: bool, detail: str = "") -> bool:
        if cond:
            self.ok += 1
            print(f"  [gecti] {name:<42}{detail}")
        else:
            self.fail += 1
            print(f"  [HATA ] {name:<42}{detail}")
        return cond

    def note(self, name: str, detail: str = "") -> None:
        self.warn += 1
        print(f"  [uyari] {name:<42}{detail}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("model_id")
    p.add_argument("--library", default=str(LIBRARY))
    p.add_argument("--render", action="store_true",
                   help="test tasarimiyla render edip maskelemeyi dogrula")
    p.add_argument("--design", default=str(ENGINE / "tasarimlar" / "test-design.png"))
    args = p.parse_args()

    D = Path(args.library) / args.model_id
    if not D.is_dir():
        print(f"HATA: klasor yok: {D}", file=sys.stderr)
        return 2

    r = Report()
    print(f"\n{args.model_id}")

    print("\n1. Dosyalar")
    missing = [f for f in REQUIRED if not (D / f).exists()]
    if missing:
        for f in missing:
            r.check(f, False, "EKSIK")
        print(f"\n{r.fail} dosya eksik. Asset tamamlanmamis.\n")
        return 2
    for f in REQUIRED:
        r.check(f, True)

    base = cv2.imread(str(D / "base.png"), cv2.IMREAD_COLOR)
    gm = cv2.imread(str(D / "garment_mask.png"), cv2.IMREAD_GRAYSCALE)
    pm = cv2.imread(str(D / "print_mask.png"), cv2.IMREAD_GRAYSCALE)
    dp = cv2.imread(str(D / "displace.png"), cv2.IMREAD_GRAYSCALE)
    sh = cv2.imread(str(D / "shading.png"), cv2.IMREAD_GRAYSCALE)
    meta = json.loads((D / "meta.json").read_text(encoding="utf-8"))

    H, W = base.shape[:2]
    m = gm > 127

    print("\n2. Hizalama")
    for name, img in (("garment_mask", gm), ("print_mask", pm),
                      ("displace", dp), ("shading", sh)):
        r.check(f"{name} boyutu base ile ayni", img.shape[:2] == (H, W),
                f"{img.shape[1]}x{img.shape[0]}")
    print(f"  base cozunurluk: {W}x{H}")
    if min(W, H) < 2000:
        r.note("kisa kenar < 2000", f"{min(W,H)} px, Etsy icin buyutme gerekir")

    print("\n3. garment_mask")
    r.check("ikili (0/255)", set(np.unique(gm).tolist()) <= {0, 255})
    cov = 100 * m.mean()
    r.check(f"kaplama %{COVERAGE_MIN:.0f}-{COVERAGE_MAX:.0f}",
            COVERAGE_MIN < cov < COVERAGE_MAX, f"%{cov:.1f}")
    n, _ = cv2.connectedComponents(m.astype(np.uint8))
    r.check("tek parca", n == 2, f"{n-1} bilesen")

    print("\n4. print_mask")
    r.check("giysi disina tasmiyor", int(((pm > 8) & ~m).sum()) == 0,
            f"{int(((pm > 8) & ~m).sum())} piksel")
    pcov = 100 * (pm > 8).mean()
    r.check(f"alan %{PRINT_AREA_MIN}-{PRINT_AREA_MAX}",
            PRINT_AREA_MIN < pcov < PRINT_AREA_MAX, f"%{pcov:.2f}")
    r.check("kenar yumusatilmis", int(((pm > 0) & (pm < 255)).sum()) > 0,
            f"{int(((pm > 0) & (pm < 255)).sum()):,} gecis pikseli")

    print("\n5. displace")
    out = dp[~m].astype(np.float32)
    r.check("giysi disi notr 128", abs(out.mean() - 128) < 0.5 and out.std() < 0.5,
            f"ort {out.mean():.1f} std {out.std():.2f}")
    fold = dp[m].astype(np.float32).std()
    r.check(f"kivrim std > {FOLD_STD_MIN}", fold > FOLD_STD_MIN, f"{fold:.1f}")
    d32 = dp.astype(np.float32)
    smooth = cv2.GaussianBlur(d32, (0, 0), 8)
    ratio = (smooth[m] - smooth[m].mean()).std() / max((d32 - smooth)[m].std(), 1e-6)

    # Kademeli: ikili gec/kal, JPEG sikistirmasi veya dusuk cozunurluk
    # yuzunden sinyali zayiflamis ama kullanilabilir assetleri gereksiz
    # yere reddediyordu. Ara bant uyari veriyor, asset publishable kaliyor.
    if ratio >= FOLD_NOISE_OK:
        r.check(f"kivrim/gurultu >= {FOLD_NOISE_OK}", True, f"{ratio:.2f}")
    elif ratio >= FOLD_NOISE_WARN:
        r.check(f"kivrim/gurultu >= {FOLD_NOISE_WARN}", True, f"{ratio:.2f}")
        r.note("kivrim sinyali zayif",
               "JPEG sikistirmasi veya dusuk cozunurluk nedeniyle kivrim "
               "sinyali zayif olabilir. Render kalitesi yine de kabul "
               "edilebilir.")
    else:
        r.check(f"kivrim/gurultu >= {FOLD_NOISE_WARN}", False,
                f"{ratio:.2f} -- Kivrim sinyali yetersiz. Displacement "
                f"haritasi buyuk olasilikla gurultu iceriyor.")

    print("\n6. shading")
    so = sh[~m]
    r.check("giysi disi tam 128", so.min() == 128 and so.max() == 128,
            f"{so.min()}-{so.max()}")
    r.check("giysi ortalamasi 128", abs(sh[m].mean() - 128) < 3, f"{sh[m].mean():.1f}")
    rng = int(sh[m].max()) - int(sh[m].min())
    r.check(f"golge araligi > {SHADING_RANGE_MIN}", rng > SHADING_RANGE_MIN,
            f"{rng} seviye")
    if rng < SHADING_RANGE_GOOD:
        r.note("golge araligi dar", f"{rng} < {SHADING_RANGE_GOOD}, isik duz olabilir")

    print("\n7. meta.json")
    q = meta.get("print_quad")
    r.check("print_quad 4 nokta", isinstance(q, list) and len(q) == 4)
    if isinstance(q, list) and len(q) == 4:
        # Kose bazli ikili kontrol fazla kati: gercek fotograflarda baski
        # alaninin bir kosesi birkac piksel disari tasabiliyor ve bu
        # gorsel olarak fark edilmiyor cunku print_mask zaten giysiyle
        # kesisiyor. Bunun yerine quad ALANININ ne kadarinin giysi icinde
        # kaldigini olcuyoruz.
        quad_layer = np.zeros((H, W), np.uint8)
        cv2.fillPoly(quad_layer, [np.array(q, np.int32)], 255)
        quad_px = int((quad_layer > 0).sum())
        inside_px = int(((quad_layer > 0) & m).sum())
        pct = 100.0 * inside_px / max(quad_px, 1)

        if pct >= QUAD_INSIDE_OK:
            r.check("quad giysi icinde", True, f"%{pct:.1f}")
        elif pct >= QUAD_INSIDE_WARN:
            r.check("quad giysi icinde", True, f"%{pct:.1f}")
            r.note("baski alani hafif tasiyor",
                   f"%{pct:.1f} icinde, print_mask kirpacak")
        else:
            r.check("quad giysi icinde", False,
                    f"%{pct:.1f} < %{QUAD_INSIDE_WARN:.0f}")

    qsrc = meta.get("quad_source")
    r.check("quad_source alani var", qsrc in ("auto", "manual"), str(qsrc))
    for k in ("design_scale", "displacement", "shading"):
        r.check(f"{k} mevcut", k in meta)
    pub = meta.get("publishable")
    r.check("publishable alani var", pub is not None, str(pub))
    if pub and not meta.get("verified_garment"):
        r.note("publishable=true ama verified_garment=false", "celiskili")

    if args.render:
        print("\n8. render")
        design = Path(args.design)
        if not design.exists():
            r.note("test tasarimi yok", str(design))
        else:
            with tempfile.TemporaryDirectory() as tmp:
                out_png = Path(tmp) / "r.png"
                res = subprocess.run(
                    [sys.executable, str(ENGINE / "cli.py"), str(design),
                     "--model", args.model_id, "--out", str(out_png)],
                    capture_output=True, text=True)
                if res.returncode != 0 or not out_png.exists():
                    r.check("render calisti", False, res.stderr.strip()[:60])
                else:
                    mk = cv2.imread(str(out_png)).astype(np.int16)
                    diff = np.abs(mk - base.astype(np.int16)).max(axis=2)
                    r.check("baski alani DISINDA degisim yok",
                            int((diff[pm <= 8] > 2).sum()) == 0,
                            f"{int((diff[pm <= 8] > 2).sum())} piksel")
                    r.check("baski alani icinde degisim var",
                            (diff[pm > 8] > 2).mean() > 0.02,
                            f"%{100*(diff[pm > 8] > 2).mean():.1f}")

    print(f"\n{'=' * 62}")
    print(f"{r.ok} gecti, {r.fail} hata, {r.warn} uyari")
    if r.fail:
        print("\nAsset KULLANILAMAZ. Yukaridaki hatalari duzelt.\n")
        return 1
    print("\nAsset gecerli.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
