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


def garment_dims(args) -> tuple[float, float]:
    """Giysinin (genislik, boy) olculeri, inc.

    --garment-width / --garment-length verilirse ONLAR kullanilir.
    Beden tablosu Bella Canvas 3001'e ait; baska marka veya oversize
    kesim icin gecerli degil. Elindeki tisortu mezurayla olcup girmek
    her zaman daha dogru:

      genislik : koltuk altindan koltuk altina, duz serili
      boy      : yakanin en yuksek noktasindan etek ucuna
    """
    w = args.garment_width if args.garment_width else BC3001_SIZES[args.size][0]
    l = args.garment_length if args.garment_length else BC3001_SIZES[args.size][1]
    return float(w), float(l)


def flatlay_body_axis(mask: np.ndarray) -> tuple[float, float, float, dict]:
    """Flatlay giysinin govde ekseni: x = slope*y + intercept, ve acisi.

    YALNIZCA FLATLAY DALI KULLANIR. Human yolu bu fonksiyonu cagirmaz.

    Yontem: KOLTUK ALTININ ALTINDAKI govde merkezlerine dogru uydurup
    yukari ekstrapole etmek. Aci ve baski merkezi AYNI kaynaktan gelir;
    ikisini ayri hesaplamak tutarsizlik yaratiyordu.

    ELENEN YONTEMLER (referans flatlay uzerinde olculdu):

      PCA          : -43.8 ... -55.9, erozyona gore kayiyor. Kollar yana
                     acik oldugu icin ana eksen govde ekseni degil.
      minAreaRect  : -27.4 ama OpenCV surumune gore aci konvansiyonu
                     degisiyor, hangi kenarin govde oldugu belirsiz.
      yaka->etek   : -21.8 ve MERKEZI 68-155 px SOLA kaydiriyordu.
                     Sebep: bu fotografta tisort kadrajin ustunden
                     kesilmis (maske y=0'da x 744-820 arasinda basliyor,
                     yani gorunen sey yaka degil kesik sag omuz).
                     Yaka bandi o kesik bolgeyi olcuyordu.

    Koltuk alti alti temiz sinyal: kesik bolge yok, kollar dahil degil,
    uzun aralikta olculuyor (referansta 446 piksel).
    """
    m = mask > 127
    ys, xs = np.where(m)
    if len(ys) == 0:
        return 0.0, 0.0, 0.0, {"reason": "bos maske"}

    y0, y1 = int(ys.min()), int(ys.max())
    height = y1 - y0 + 1

    widths = np.array([
        (np.where(m[y])[0].max() - np.where(m[y])[0].min() + 1)
        if m[y].any() else 0 for y in range(y0, y1 + 1)
    ])
    y_widest = y0 + int(np.argmax(widths))

    armpit = y_widest
    for y in range(y_widest, y1):
        row = np.where(m[y])[0]
        if len(row) == 0:
            continue
        if len(np.split(row, np.where(np.diff(row) > 1)[0] + 1)) > 1:
            armpit = y
            break

    pts = []
    lo = min(armpit + max(10, height // 40), y1 - 2)
    hi = max(lo + 10, y1 - int(height * 0.08))
    for yy in range(lo, min(hi, y1)):
        row = np.where(m[yy])[0]
        if len(row) == 0:
            continue
        blk = max(np.split(row, np.where(np.diff(row) > 1)[0] + 1), key=len)
        pts.append((yy, blk.mean()))

    if len(pts) < 10:
        # Yeterli veri yok: dikey eksen varsay, giysi kutusunun merkezi.
        return 0.0, float((xs.min() + xs.max()) / 2), 0.0, {
            "reason": "yetersiz govde satiri", "n": len(pts)}

    arr = np.array(pts, dtype=np.float64)
    slope, intercept = np.polyfit(arr[:, 0], arr[:, 1], 1)
    angle = float(np.degrees(np.arctan(slope)))

    return float(slope), float(intercept), angle, {
        "armpit": armpit, "y_widest": y_widest,
        "fit_lo": int(arr[0, 0]), "fit_hi": int(arr[-1, 0]),
        "range": (int(arr[0, 0]), int(arr[-1, 0])), "n": len(pts)}


def rotate_quad(cx: float, cy: float, w: float, h: float,
                angle_deg: float) -> list[list[int]]:
    """Merkezi (cx,cy) olan w x h dikdortgeni angle_deg dondurur.

    Ciktinin 4 nokta olmasi compositor icin yeterli: getPerspectiveTransform
    keyfi dortgeni destekliyor, render mantigi degismiyor.
    """
    a = np.radians(angle_deg)
    ca, sa = np.cos(a), np.sin(a)
    corners = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    out = []
    for px, py in corners:
        # Saat yonunun tersine donus; ekran koordinatinda y asagi.
        rx = px * ca - py * sa
        ry = px * sa + py * ca
        out.append([int(round(cx + rx)), int(round(cy + ry))])
    return out


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
    p.add_argument("--garment-width", type=float,
                   help="giysinin GERCEK genisligi (inc, koltukalti-koltukalti). "
                        "Verilirse --size tablosu kullanilmaz.")
    p.add_argument("--garment-length", type=float,
                   help="giysinin GERCEK boyu (inc, yaka-etek)")
    p.add_argument("--size", choices=list(BC3001_SIZES), default="M",
                   help="BC3001 bedeni (varsayilan M)")
    p.add_argument("--width", type=float, help="giysi genisligi inc (bedeni ezer)")
    p.add_argument("--length", type=float, help="giysi boyu inc (bedeni ezer)")
    p.add_argument("--print-w", type=float, default=PRINT_AREA_IN[0])
    p.add_argument("--print-h", type=float, default=PRINT_AREA_IN[1])
    p.add_argument("--collar-drop", type=float, default=COLLAR_DROP_IN)
    p.add_argument("--top-gap", type=float, default=TOP_GAP_IN)
    p.add_argument("--scale-from", choices=["auto", "width", "length"], default="auto")
    p.add_argument("--flatlay", action="store_true",
                   help="ustten cekim: spec olcusu yerine dogrudan oran kullan")
    p.add_argument("--flatlay-angle", type=float,
                   help="flatlay: govde acisini elle ver (derece, dikeyden)")
    p.add_argument("--min-angle", type=float, default=2.0,
                   help="flatlay: bu acinin altinda donus uygulanmaz")
    p.add_argument("--flatlay-center", type=float, default=-0.10,
                   help="flatlay: baski merkezi = koltukalti + oran*baski_yuksekligi")
    p.add_argument("--flatlay-top", type=float, default=0.20,
                   help="flatlay: baski ust kenari = giysi_ust + oran*yukseklik")
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

    # --- FLATLAY DALI -------------------------------------------------
    # Ustten cekimde BC3001 spec olculeri gecersiz: tisort duz serili,
    # kollar yana yayilmis, hangi piksel olcusunun spec'teki 20 inclik
    # "width" oldugu belirsiz. Insan fotografinda govde genisligi giyen
    # kisinin bedenine oturuyor, flatlay'de oturmuyor.
    #
    # Bu yuzden mutlak olcek (px/inc) hic hesaplanmiyor. Quad dogrudan
    # orandan: govde genisliginin %60'i (12" baski / 20" giysi), yukseklik
    # baski alaninin kendi en-boy oranindan.
    #
    # Insan dali bu koddan HIC etkilenmiyor -- --flatlay verilmezse
    # asagidaki eski yol aynen calisiyor.
    if args.flatlay:
        # garment_metrics insan fotografi icin yazildi ve flatlay'de
        # yaniltiyor: kollar yana yayildigi icin "koltuk alti" tespiti
        # govde yerine kol acikligini buluyor. Ayrica flatlay'de giysi
        # egik durabiliyor (referansta merkez 701 -> 429 kayiyor).
        # Bu yuzden govde bolgesi burada AYRI olculuyor.
        ys_, xs_ = np.where(mask > 127)
        fy0, fy1 = int(ys_.min()), int(ys_.max())
        fh = fy1 - fy0 + 1

        # Govde: yukseklik boyunca en genis SUREKLI blogun tarandigi bant.
        # Ust %25 yaka/omuz, alt %25 etek -- ikisi de govde genisligini
        # temsil etmiyor. Orta bantta olcup medyan aliyoruz.
        # Govde genisligi KOLTUK ALTININ BELIRGIN ALTINDAN olculur.
        # Koltuk altina yakin satirlarda kollar hala govdeyle birlesik:
        # referansta y=455'te 798 px olculuyordu, gercek govde ~580.
        # Tek satir yerine bir bandin medyani aliniyor.
        _s0, _i0, _a0, _d0 = flatlay_body_axis(mask)
        _ap = _d0.get("armpit")
        if _ap is not None:
            lo_r = min(int(_ap + fh * 0.06), fy1 - 5)
            hi_r = min(int(_ap + fh * 0.30), fy1 - 2)
        else:
            lo_r, hi_r = int(fy0 + fh * 0.45), int(fy0 + fh * 0.70)
        rows = []
        for yy in range(lo_r, max(lo_r + 5, hi_r)):
            row = np.where(mask[yy] > 127)[0]
            if len(row) == 0:
                continue
            blk = max(np.split(row, np.where(np.diff(row) > 1)[0] + 1), key=len)
            rows.append((len(blk), int(blk.mean()), yy))
        if not rows:
            print("HATA: flatlay govde bolgesi olculemedi.", file=sys.stderr)
            return 1

        body = int(np.median([r[0] for r in rows]))
        cx_auto = int(np.median([r[1] for r in rows]))

        qw = body * (args.print_w / garment_dims(args)[0])
        qh = qw * (args.print_h / args.print_w)
        cx = args.center_x if args.center_x is not None else cx_auto
        # Dikey: govde bandinin ustunden basla. Yaka cukuru flatlay
        # maskesinde kapali oldugu icin oran kullaniliyor.
        # Dikey konum KOLTUK ALTINA gore. Giysi kutusunun tepesini
        # referans almak kirilgan: bu fotografta tisort kadrajin
        # ustunden kesilmis, yani kutunun tepesi omuz cizgisi degil.
        # Koltuk alti maskede her zaman tespit edilebilen fiziksel bir
        # isaret.
        #
        # -0.10 olculerek secildi (referans flatlay, quad'in giysi
        # icinde kalan orani):
        #   -0.20 %93.8   -0.15 %96.6   -0.10 %97.6
        #   -0.05 %97.5    0.00 %96.0   +0.05 %93.9
        _slope0, _inter0, _ang0, _diag0 = flatlay_body_axis(mask)
        _armpit = _diag0.get("armpit")
        if args.top_y is not None:
            top = args.top_y
        elif _armpit is not None:
            top = int(round(_armpit + qh * args.flatlay_center - qh / 2.0))
        else:
            top = int(round(fy0 + fh * args.flatlay_top))
        # Flatlay'de tisort kadraj icinde donebiliyor. Eksene paralel
        # bir quad tasarimi tisorte gore YAMUK gosteriyordu. Quad'i
        # govde eksenine hizaliyoruz -- compositor'un mevcut perspektif
        # warp'i keyfi dortgeni zaten destekliyor, render mantigi
        # degismiyor.
        slope, intercept, angle, diag = flatlay_body_axis(mask)
        if args.flatlay_angle is not None:
            angle = args.flatlay_angle
        quad_cy = top + qh / 2.0
        # Merkez, quad'in KENDI dikey konumunda eksen uzerinde.
        # Sabit bir bant medyani kullanmak donuk giyside yanlis yer
        # veriyordu: govde merkezi yukseklige gore kayiyor.
        if args.center_x is None and diag.get("reason") is None:
            # Eksen KOLTUK ALTI ALTINDAN uyduruluyor; baski alani ise
            # gogus hizasinda, yani olcum araliginin USTUNDE. Serbest
            # ekstrapolasyon hata biriktiriyor: referansta y=302'ye
            # uzatmak merkezi 32 px fazla saga tasidi (%94.5 -> dx=-60
            # ile %97.8). Bu yuzden olcum araliginin disina cikildiginda
            # eksen sabit devam ediyor.
            eval_y = max(quad_cy, float(diag.get("fit_lo", quad_cy)))
            cx = intercept + slope * eval_y
        if abs(angle) < args.min_angle:
            # Kucuk aci: donusu uygulamak yuvarlama gurultusu disinda
            # bir sey degistirmez. Duz flatlay davranisi korunuyor.
            quad = [[int(round(cx - qw / 2)), int(top)],
                    [int(round(cx + qw / 2)), int(top)],
                    [int(round(cx + qw / 2)), int(round(top + qh))],
                    [int(round(cx - qw / 2)), int(round(top + qh))]]
            applied = 0.0
        else:
            quad = rotate_quad(cx, quad_cy, qw, qh, angle)
            applied = angle

        print(f"\n{args.model_id}")
        print("  FLATLAY MODU -- spec olcusu kullanilmadi")
        print(f"  giysi           : y {fy0}-{fy1}  yukseklik {fh} px")
        print(f"  govde genisligi : {body} px  (orta bant medyani)")
        print(f"  govde merkezi   : x {cx_auto}")
        print(f"  baski/giysi oran: %{args.print_w / garment_dims(args)[0] * 100:.0f}")
        print(f"  baski alani     : {qw:.0f} x {qh:.0f} px")
        print(f"  govde acisi     : {angle:+.2f} derece (dikeyden)")
        print(f"  uygulanan donus : {applied:+.2f} derece"
              f"{'  (esik alti, atlandi)' if applied == 0.0 and abs(angle) >= 0.01 else ''}")
        print(f"  print_quad      : {quad}")

        return finish(args, model_dir, meta_path, mask, quad,
                      source="auto-flatlay",
                      metrics={"guides": [fy0, fy1],
                               "meta": {"print_area_inches": [args.print_w, args.print_h],
                                        "garment_size": args.size,
                                        "layout": "flatlay"}})

    w_in, l_in = garment_dims(args)
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
    _src = "olculdu" if (args.garment_width or args.garment_length) else f"beden {args.size}"
    print(f"  giysi olcusu   : {w_in} x {l_in} inc  ({_src})")
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
