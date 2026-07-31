#!/usr/bin/env python3
"""base.png -> garment_mask.png  (otomatik)

Kütüphanedeki tek elle iş bu maskeyi çıkarmaktı. 30 model için ~5 saat
GIMP demekti; bu araç onu ortadan kaldırıyor.

    python tools/auto_mask.py bella-canvas-3001/female-front-001
    python tools/auto_mask.py <model> --debug        # kontrol kaplaması yaz
    python tools/auto_mask.py <model> --method cloth # ML segmentasyon

İki yöntem
----------
classic (varsayılan, ek bağımlılık yok)
    Kontrollü stüdyo çekimi için tasarlandı: beyaz tişört + gri fon.
    Fon kenarlardan flood fill ile bulunur, kişi = fon değil.
    Kişi içinde tişört = DÜŞÜK doygunluk + YÜKSEK parlaklık.
    Ten daha doygun, saç daha karanlık -- ikisi de bu eşiğin dışında kalır.

cloth (rembg gerekir)
    pip install rembg onnxruntime
    u2net_cloth_seg modeli giysiyi doğrudan segmentler. Renkli tişörtte
    ve karmaşık arka planda classic'ten iyi. İlk çalıştırmada model
    indirir (~170 MB).

Her iki yöntemde de sonucu GÖZLE KONTROL ET. --debug kaplaması bunun için.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ENGINE = Path(__file__).resolve().parent.parent
LIBRARY = ENGINE / "assets" / "base-library"

WORK_MAX = 1400  # segmentasyon bu çözünürlükte yapılır, sonra büyütülür


# --------------------------------------------------------------------------
# classic
# --------------------------------------------------------------------------

def background_mask(bgr: np.ndarray, tolerance: int) -> np.ndarray:
    """Satır bazlı fon modeli.

    İlk sürümde kenarlardan flood fill kullanıyordum; kumaş kenarındaki
    yumuşak geçişten sızıp tişörtün içine taşıyordu. Bunun yerine fonun
    SATIR BAŞINA referans rengini kenar bantlarından ölçüyoruz -- stüdyo
    fonlarındaki dikey gradyanı doğal olarak takip eder ve sızıntı
    yapacak bir yayılma mekanizması yok.

    Ölçüm Lab uzayında yapılıyor: gri fonla beyaz kumaş arasındaki fark
    esas olarak parlaklık farkı ve Lab bunu RGB'den daha doğru ayırıyor.
    """
    h, w = bgr.shape[:2]
    lab = cv2.cvtColor(cv2.GaussianBlur(bgr, (0, 0), 1), cv2.COLOR_BGR2LAB).astype(np.float32)

    band = max(4, int(w * 0.05))
    edges = np.concatenate([lab[:, :band, :], lab[:, -band:, :]], axis=1)
    # Satır başına medyan: kişi kadrajın ortasında olduğu için kenar
    # bantları neredeyse tamamen fondur.
    row_ref = np.median(edges, axis=1)                      # h x 3
    row_ref = cv2.GaussianBlur(row_ref, (1, 31), 0)         # dikey yumuşatma

    distance = np.linalg.norm(lab - row_ref[:, None, :], axis=2)
    bg = (distance < tolerance).astype(np.uint8) * 255

    # Sadece kenara BAĞLI olanlar gerçekten fondur; tişörtün içinde
    # tesadüfen fon rengine yakın bir piksel varsa elenir.
    n, labels = cv2.connectedComponents((bg > 127).astype(np.uint8), connectivity=8)
    border = set(np.unique(np.concatenate([
        labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]])))
    border.discard(0)

    keep = np.isin(labels, list(border)) if border else np.zeros_like(bg, bool)
    return (keep.astype(np.uint8) * 255)


def largest_component(mask: np.ndarray) -> np.ndarray:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(
        (mask > 127).astype(np.uint8), connectivity=8)
    if n <= 1:
        return mask
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return np.where(labels == biggest, 255, 0).astype(np.uint8)


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """İç boşlukları doldurur (kırışık gölgesinin açtığı delikler).

    Dış arka planı (0,0)'dan 255 ile doldururuz; geriye 0 olarak yalnızca
    kenara BAĞLI OLMAYAN iç boşluklar kalır. Onları maskeye ekleriz.

    1 piksel sıfır dolgu şart: maske köşeye değiyorsa flood fill hiçbir
    şey yapamaz ve fonksiyon tüm kareyi doldurur.
    """
    padded = cv2.copyMakeBorder(mask, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    h, w = padded.shape[:2]

    flood = padded.copy()
    cv2.floodFill(flood, np.zeros((h + 2, w + 2), np.uint8), (0, 0), 255)

    holes = cv2.bitwise_not(flood)          # yalnızca iç boşluklar 255
    filled = cv2.bitwise_or(padded, holes)
    return filled[1:-1, 1:-1]


def classic_mask(bgr: np.ndarray, s_max: int, v_min: int, tolerance: int,
                 debug: dict | None = None) -> np.ndarray:
    bg = background_mask(bgr, tolerance)
    person = cv2.bitwise_not(bg)
    person = cv2.morphologyEx(person, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
    person = largest_component(person)

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    sat, val = hsv[..., 1], hsv[..., 2]

    # Beyaz kumaş: düşük doygunluk, yüksek parlaklık.
    # Ten tonu doygunluğu genelde 40'ın üzerinde, saç parlaklığı 100'ün altında.
    garment = ((sat < s_max) & (val > v_min)).astype(np.uint8) * 255
    garment = cv2.bitwise_and(garment, person)

    k_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
    garment = cv2.morphologyEx(garment, cv2.MORPH_OPEN, k_open)
    garment = cv2.morphologyEx(garment, cv2.MORPH_CLOSE, k_close)
    garment = largest_component(garment)
    garment = fill_holes(garment)

    if debug is not None:
        debug["person"] = person
        debug["raw_garment"] = garment.copy()

    return garment


# --------------------------------------------------------------------------
# cloth (rembg)
# --------------------------------------------------------------------------

def cloth_mask(bgr: np.ndarray) -> np.ndarray:
    try:
        from rembg import new_session, remove
    except ImportError:
        raise SystemExit(
            "rembg kurulu değil.\n"
            "  pip install rembg onnxruntime\n"
            "veya --method classic kullan."
        )

    session = new_session("u2net_cloth_seg")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    out = remove(rgb, session=session, only_mask=True)

    mask = np.array(out)

    # Cikti RGBA gelebiliyor. Kanal 0/1/2 ayni maskeyi tasiyor; kanal 3
    # alfa ve her yerde 255 -- onu almak tum kareyi maske yapar (olculdu).
    if mask.ndim == 3:
        mask = mask[..., 0]

    # u2net_cloth_seg ucu segmenti DIKEY ISTIFLEYEREK donduruyor:
    # ciktinin yuksekligi girdinin tam 3 kati ve siralama
    #   [0]  ust govde   <- tisort, bize gereken bu
    #   [1]  alt govde
    #   [2]  tam govde
    # Bunu kanal sanip mask[..., 0] almak, 3H satiri H'ye sikistirdigi
    # icin kullanilamaz bir maske uretiyordu (olculdu: %14 kaplama,
    # dogru bant ile %43).
    h = bgr.shape[0]
    if mask.shape[0] == h * 3:
        mask = mask[:h]
    elif mask.shape[0] != h:
        raise SystemExit(
            f"Beklenmeyen segmentasyon ciktisi: {mask.shape}, girdi yuksekligi {h}.\n"
            "rembg surumu degismis olabilir; --method classic kullan."
        )

    mask = np.where(mask > 127, 255, 0).astype(np.uint8)
    return fill_holes(largest_component(mask))


# --------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("model_id", help="ör. bella-canvas-3001/female-front-001")
    p.add_argument("--library", default=str(LIBRARY))
    p.add_argument("--method", choices=["classic", "cloth"], default="classic")
    p.add_argument("--s-max", type=int, default=45,
                   help="tişört için üst doygunluk eşiği (0-255)")
    p.add_argument("--v-min", type=int, default=110,
                   help="tişört için alt parlaklık eşiği (0-255)")
    p.add_argument("--tolerance", type=int, default=12,
                   help="fon renk mesafesi eşiği (Lab)")
    p.add_argument("--debug", action="store_true", help="kontrol kaplaması yaz")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    model_dir = Path(args.library) / args.model_id
    base_path = model_dir / "base.png"
    out_path = model_dir / "garment_mask.png"

    if not base_path.exists():
        print(f"HATA: {base_path} yok.", file=sys.stderr)
        return 1
    if out_path.exists() and not args.force:
        print(f"{out_path.name} zaten var. Üzerine yazmak için --force.")
        return 1

    full = cv2.imread(str(base_path), cv2.IMREAD_COLOR)
    fh, fw = full.shape[:2]

    scale = min(1.0, WORK_MAX / max(fh, fw))
    work = (cv2.resize(full, (int(fw * scale), int(fh * scale)),
                       interpolation=cv2.INTER_AREA) if scale < 1.0 else full)

    debug: dict = {} if args.debug else None

    if args.method == "cloth":
        mask = cloth_mask(work)
    else:
        mask = classic_mask(work, args.s_max, args.v_min, args.tolerance, debug)

    # Tam çözünürlüğe geri büyüt, kenarı temizle
    if scale < 1.0:
        mask = cv2.resize(mask, (fw, fh), interpolation=cv2.INTER_LINEAR)
    mask = np.where(cv2.GaussianBlur(mask, (0, 0), 2) > 127, 255, 0).astype(np.uint8)

    coverage = float((mask > 127).sum()) / (fh * fw) * 100
    cv2.imwrite(str(out_path), mask)

    print(f"\n{args.model_id}  ({fw}x{fh})")
    print(f"  yöntem            : {args.method}")
    print(f"  kare kaplama      : %{coverage:.1f}")
    print(f"  yazıldı           : {out_path}")

    # Torso kadrajlı bir çekimde tişört karenin kabaca %25-60'ını kaplar.
    # Bu aralığın dışı neredeyse her zaman kötü segmentasyon demek.
    if coverage < 15:
        print("\n  UYARI: maske çok küçük. Eşikler fazla dar olabilir --")
        print("  --s-max 60 --v-min 90 dene, ya da --method cloth.")
    elif coverage > 70:
        print("\n  UYARI: maske çok büyük. Fon veya ten de maskeye girmiş --")
        print("  --s-max 30 --v-min 140 dene, ya da --method cloth.")

    if args.debug:
        overlay = full.copy()
        green = np.zeros_like(overlay)
        green[..., 1] = 255
        m3 = (mask > 127)[..., None]
        overlay = np.where(m3, (overlay * 0.55 + green * 0.45).astype(np.uint8), overlay)
        dbg = model_dir / "_debug_mask.png"
        cv2.imwrite(str(dbg), overlay)
        print(f"  kontrol kaplaması : {dbg}")

    print("\n  Sonucu GÖZLE KONTROL ET. Yaka, koltuk altı ve etek çizgisi")
    print("  doğru mu? Değilse eşikleri oynat veya GIMP'te rötuşla.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
