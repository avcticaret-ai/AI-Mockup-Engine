#!/usr/bin/env python3
"""garment_mask.png -> meta.json icinde print_quad

OTOMATIK (varsayilan)
    python tools/derive_quad.py bella-canvas-3001/female-front-001
    python tools/derive_quad.py <model> --size L
    python tools/derive_quad.py <model> --top-y 460      # yalnizca dikey konum
    python tools/derive_quad.py <model> --dry-run        # yazmadan gor

MANUEL OVERRIDE
    python tools/derive_quad.py bella-canvas-3001/female-front-004 \
        --left 1200 --top 350 --right 1650 --bottom 950

    Dort kenar BIRDEN verilmeli. Verilirse otomatik hesap tamamen
    atlanir; koordinatlar dogrudan print_quad olur. Onizleme yine
    uretilir ve meta.json'a quad_source="manual" yazilir.

NEDEN MANUEL GEREKIYOR
    Otomatik hesap giysinin duz serili oldugunu varsayan spec olculerine
    dayaniyor. Gercek fotograflarda perspektif, drape ve yaka cukurunun
    maskeden tespit edilememesi konumu kaydirabiliyor. Maske dogru olsa
    bile baski alani yanlis oturuyorsa cozum onizlemeye bakip koordinati
    elle vermek.

IS AKISI
    1. python tools/derive_quad.py <model>              otomatik dene
    2. _quad_preview.png'ye bak
    3. yanlissa: --left/--top/--right/--bottom ile duzelt
    4. python tools/prepare_base.py <model> --force     haritalari yenile
    5. python tools/verify_asset.py <model> --render    dogrula

NEDEN BU ARAC VAR
    calibrate_quad.py quad'i YAZAR ama HESAPLAMAZ. Once her asset icin
    govde genisligi elle olculup inc'e cevriliyordu; asset basina ~15
    dakika ve hataya acik.

YONTEM
    baski_px = (baski_inc / giysi_genisligi_inc) x olculen_govde_px

    Mutlak px/inc kullanilmiyor: giysinin nasil sunuldugune bagli ve
    referans fotografta iki tahmin %36 ayristi. Oran ise sunumdan
    bagimsiz -- 12 inclik baski her zaman 20 inclik giysinin %60'idir.
    Dikey konum ayri olcekten (boy) geliyor cunku askida cekimde yatay
    ve dikey px/inc esit degil.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

ENGINE = Path(__file__).resolve().parent.parent
LIBRARY = ENGINE / "assets" / "base-library"

# Bella Canvas 3001 beden tablosu (inç, düz ölçüm).
# Baska urun eklenirse burasi degil, --width/--length ile verilir.
BC3001_SIZES = {
    "S":  (18.0, 28.0),
    "M":  (20.0, 29.0),
    "L":  (22.0, 30.0),
    "XL": (24.0, 31.0),
}

PRINT_AREA_IN = (12.0, 16.0)   # BC3001 on baski alani
COLLAR_DROP_IN = 3.0           # omuz hizasindan on yaka cukuruna
TOP_GAP_IN = 2.5               # yaka cukurundan baskinin ustune


def garment_metrics(mask: np.ndarray) -> dict:
    """Maskeden giysi geometrisini olcer."""
    m = mask > 127
    ys, xs = np.where(m)
    if len(ys) == 0:
        raise SystemExit("garment_mask.png bos.")

    y0, y1 = int(ys.min()), int(ys.max())
    height = y1 - y0 + 1

    widths = np.zeros(height, dtype=int)
    centers = np.zeros(height, dtype=int)
    for i in range(height):
        row = np.where(m[y0 + i])[0]
        if len(row):
            widths[i] = row.max() - row.min() + 1
            centers[i] = (row.max() + row.min()) // 2

    # Koltuk alti: en genis satirdan ASAGI dogru, kollarin govdeden
    # ayrildigi ilk satir. Yukaridan aramak tepedeki birkac piksellik
    # yaka ucuna takiliyor.
    widest = int(np.argmax(widths))
    armpit = None
    for i in range(widest, height):
        row = np.where(m[y0 + i])[0]
        if len(row) == 0:
            continue
        if len(np.split(row, np.where(np.diff(row) > 1)[0] + 1)) > 1:
            armpit = i
            break

    # Giysi "width" olcusu KOLTUK ALTINDAN KOLTUK ALTINA govde genisligidir,
    # kol ucundan kol ucuna DEGIL. En genis satiri kullanmak sleeve
    # malzemesini de sayiyordu: referans fotografta 976 px (kol ucu) yerine
    # 556 px (govde) olculmeli. Bu yuzden koltuk altinin biraz ALTINDAN,
    # kollar ayrildiktan sonraki en genis SUREKLI blogu oluyoruz.
    if armpit is not None:
        probe = min(armpit + max(10, height // 40), height - 1)
    else:
        probe = int(height * 0.55)
    row = np.where(m[y0 + probe])[0]
    body_block = max(np.split(row, np.where(np.diff(row) > 1)[0] + 1), key=len) \
        if len(row) else np.array([0])
    body_width = int(len(body_block))
    body_center = int(body_block.mean()) if len(row) else int(m.shape[1] // 2)

    return {
        "y0": y0, "y1": y1, "height": height,
        "widest_row": y0 + widest,
        "widest_width": int(widths.max()),
        "armpit_row": (y0 + armpit) if armpit is not None else None,
        "probe_row": y0 + probe,
        "armpit_width": body_width,
        "center_x": body_center,
    }


def finish(args, model_dir, meta_path, mask, quad, source, info=None,
           problems=None, metrics=None):
    """Onizleme yaz, kaliteyi olc, meta.json'a kaydet.

    Otomatik ve manuel yol ayni fonksiyonu kullaniyor -- boylece
    onizleme, dogrulama ve meta yazma davranisi iki yolda birebir ayni.
    """
    problems = list(problems or [])
    m = mask > 127
    H, W = mask.shape[:2]

    qmask = np.zeros((H, W), np.uint8)
    cv2.fillPoly(qmask, [np.array(quad, np.int32)], 255)
    quad_px = int((qmask > 0).sum())
    inside_pct = 100.0 * int(((qmask > 0) & m).sum()) / max(quad_px, 1)

    if source == "manual":
        print(f"\n{args.model_id}")
        print("  MANUEL OVERRIDE -- otomatik hesap atlandi")
        print(f"  print_quad      : {quad}")
        if info:
            print(f"  baski alani     : {info['genislik']} x {info['yukseklik']} px")

    print(f"  giysi icinde    : %{inside_pct:.1f}")

    if inside_pct < 95.0:
        problems.append(
            f"quad'in yalnizca %{inside_pct:.0f}'i giysi icinde")

    if problems:
        print("\n  UYARILAR:")
        for pr in problems:
            print(f"    - {pr}")

    if args.preview:
        prev = cv2.imread(str(model_dir / "base.png"), cv2.IMREAD_COLOR)
        if prev is not None:
            overlay = prev.copy()
            cv2.fillPoly(overlay, [np.array(quad, np.int32)], (0, 220, 0))
            prev = cv2.addWeighted(overlay, 0.25, prev, 0.75, 0)
            cv2.polylines(prev, [np.array(quad, np.int32)], True, (0, 200, 0), 3)
            for y in (metrics or {}).get("guides", []):
                cv2.line(prev, (0, y), (W, y), (255, 160, 0), 2)
            cv2.putText(prev, f"quad_source: {source}", (16, 34),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                        (0, 200, 0) if source == "auto" else (60, 160, 255), 2)
            out = model_dir / "_quad_preview.png"
            cv2.imwrite(str(out), prev)
            print(f"\n  onizleme        : {out}")

    if args.dry_run:
        print("\n  --dry-run: meta.json degistirilmedi\n")
        return 0

    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta["print_quad"] = quad
    meta["quad_source"] = source
    if metrics:
        meta.update(metrics.get("meta", {}))
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    print("\n  meta.json guncellendi")
    print(f"  quad_source     : {source}\n")

    return 1 if problems else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("model_id")
    p.add_argument("--library", default=str(LIBRARY))
    p.add_argument("--size", choices=list(BC3001_SIZES), default="M",
                   help="BC3001 bedeni (varsayilan M)")
    p.add_argument("--width", type=float, help="giysi genisligi inc (bedeni ezer)")
    p.add_argument("--length", type=float, help="giysi boyu inc (bedeni ezer)")
    p.add_argument("--print-w", type=float, default=PRINT_AREA_IN[0])
    p.add_argument("--print-h", type=float, default=PRINT_AREA_IN[1])
    p.add_argument("--collar-drop", type=float, default=COLLAR_DROP_IN)
    p.add_argument("--top-gap", type=float, default=TOP_GAP_IN)
    p.add_argument("--scale-from", choices=["auto", "width", "length"], default="auto")
    p.add_argument("--top-y", type=int, help="baski ust kenari (piksel), hesabi ezer")
    p.add_argument("--center-x", type=int, help="baski merkezi (piksel), hesabi ezer")

    man = p.add_argument_group(
        "manuel override",
        "DORDU BIRDEN verilirse otomatik hesap tamamen atlanir ve bu "
        "dikdortgen dogrudan print_quad olur. Onizleme yine uretilir.")
    man.add_argument("--left", type=int, help="sol kenar (piksel)")
    man.add_argument("--top", type=int, help="ust kenar (piksel)")
    man.add_argument("--right", type=int, help="sag kenar (piksel)")
    man.add_argument("--bottom", type=int, help="alt kenar (piksel)")
    p.add_argument("--preview", action="store_true", default=True)
    p.add_argument("--no-preview", dest="preview", action="store_false")
    p.add_argument("--dry-run", action="store_true", help="meta.json'a yazma")
    args = p.parse_args()

    model_dir = Path(args.library) / args.model_id
    mask_path = model_dir / "garment_mask.png"
    meta_path = model_dir / "meta.json"

    if not mask_path.exists():
        print(f"HATA: {mask_path} yok. Once tools/auto_mask.py calistir.",
              file=sys.stderr)
        return 1

    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)

    # --- MANUEL OVERRIDE ---------------------------------------------
    # Dort kenar birden verildiyse olcum ve olcek hesabi tamamen atlanir.
    # Otomatik tahmin bazi gercek fotograflarda yanlis konumlaniyor
    # (perspektif, giysinin sunumu, yaka cukurunun tespit edilememesi);
    # o durumda kullanici onizlemeye bakip koordinati dogrudan veriyor.
    manual = [args.left, args.top, args.right, args.bottom]
    if any(v is not None for v in manual):
        if any(v is None for v in manual):
            eksik = [n for n, v in zip(("--left", "--top", "--right", "--bottom"),
                                       manual) if v is None]
            print(f"HATA: manuel override icin DORT kenar da gerekli. "
                  f"Eksik: {', '.join(eksik)}", file=sys.stderr)
            return 1
        if args.left >= args.right or args.top >= args.bottom:
            print("HATA: --left < --right ve --top < --bottom olmali.",
                  file=sys.stderr)
            return 1

        quad = [[args.left, args.top], [args.right, args.top],
                [args.right, args.bottom], [args.left, args.bottom]]
        return finish(args, model_dir, meta_path, mask, quad,
                      source="manual", info={
                          "genislik": args.right - args.left,
                          "yukseklik": args.bottom - args.top,
                      })

    g = garment_metrics(mask)

    w_in, l_in = BC3001_SIZES[args.size]
    if args.width:
        w_in = args.width
    if args.length:
        l_in = args.length

    ppi_w = g["armpit_width"] / w_in
    ppi_l = g["height"] / l_in
    disagree = abs(ppi_w - ppi_l) / max(ppi_l, 1e-6) * 100

    # Baski genisligi ORANDAN turetiliyor, mutlak olcekten degil:
    #
    #   baski_px = (baski_inc / giysi_genisligi_inc) x olculen_govde_px
    #
    # Sebep: mutlak px/inc, giysinin nasil sunuldugune bagli. Referans
    # fotografta (askida cekim) genislikten 27.8, boydan 43.7 px/inc
    # cikti -- %57 ayrisma. Hangisini secersen sec baski alani yanlis
    # boyutta oluyordu.
    #
    # Oran ise sunumdan BAGIMSIZ: 12 inclik baski, 20 inclik bir giysinin
    # genisliginin her zaman %60'idir. Giysi asili da olsa giyilmis de
    # olsa gorsel olarak dogru oran korunur.
    width_ratio = args.print_w / w_in
    qw = g["armpit_width"] * width_ratio
    qh = qw * (args.print_h / args.print_w)

    if args.scale_from == "width":
        ppi, src = ppi_w, "genislik"
    elif args.scale_from == "length":
        ppi, src = ppi_l, "boy"
    else:
        ppi, src = qw / args.print_w, "orandan"

    # Dikey konum: yaka dususu + bosluk. Bunlar inc cinsinden verildigi
    # icin baski alaninin kendi olcegiyle piksele cevriliyor.
    # Dikey konum icin DIKEY olcek. Yatay olcegi kullanmak referans
    # fotografta baski alanini 174 px yukari kaydiriyordu: askida
    # cekimde govde yatayda daralirken boy korunuyor, yani iki eksenin
    # px/inc degeri ayni degil. Yatay boyut yatay olcekten, dikey konum
    # dikey olcekten gelir.
    cx = args.center_x if args.center_x is not None else g["center_x"]
    top = args.top_y if args.top_y is not None else int(round(
        g["y0"] + (args.collar_drop + args.top_gap) * ppi_l))

    quad = [
        [int(round(cx - qw / 2)), int(top)],
        [int(round(cx + qw / 2)), int(top)],
        [int(round(cx + qw / 2)), int(round(top + qh))],
        [int(round(cx - qw / 2)), int(round(top + qh))],
    ]

    print(f"\n{args.model_id}")
    print(f"  giysi          : y {g['y0']}-{g['y1']}  yukseklik {g['height']} px")
    print(f"  en genis satir : y {g['widest_row']}  {g['widest_width']} px (kol ucu)")
    print(f"  koltuk alti    : y {g['armpit_row']}")
    print(f"  govde genisligi: {g['armpit_width']} px  (y {g['probe_row']})")
    print(f"  beden {args.size:<3}      : {w_in} x {l_in} inc")
    print()
    print(f"  olcek (genislik): {ppi_w:6.1f} px/inc")
    print(f"  olcek (boy)     : {ppi_l:6.1f} px/inc")
    print(f"  uyumsuzluk      : %{disagree:.0f}")
    print(f"  kullanilan      : {ppi:6.1f} px/inc  ({src})")
    print()
    print(f"  baski/giysi oran: %{width_ratio*100:.0f}  "
          f"({args.print_w}\" / {w_in}\")")
    print(f"  baski alani     : {qw:.0f} x {qh:.0f} px  "
          f"({args.print_w}x{args.print_h} inc)")
    print(f"  print_quad      : {quad}")

    # Kalite kontrolleri
    problems = []
    if disagree > 20:
        problems.append(
            f"olcek tahminleri %{disagree:.0f} ayrisiyor. Fotografta perspektif "
            f"olabilir veya beden yanlis. --size ile dogru bedeni ver.")

    guides = [g["y0"]] + ([g["armpit_row"]] if g["armpit_row"] else [])
    return finish(args, model_dir, meta_path, mask, quad, source="auto",
                  problems=problems,
                  metrics={"guides": guides,
                           "meta": {"print_area_inches": [args.print_w, args.print_h],
                                    "pixels_per_inch": round(ppi, 2),
                                    "garment_size": args.size}})


if __name__ == "__main__":
    raise SystemExit(main())
