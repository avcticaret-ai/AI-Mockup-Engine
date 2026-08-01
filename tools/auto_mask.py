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

WORK_MAX = 1400

# Kabul edilebilir maske kaplama araligi (kare yuzdesi). auto modu
# bir yontemin basarili sayilip sayilmayacagina buna gore karar veriyor.
COVERAGE_MIN, COVERAGE_MAX = 15.0, 70.0  # segmentasyon bu çözünürlükte yapılır, sonra büyütülür


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

def flatlay_mask(bgr: np.ndarray, debug: dict | None = None) -> np.ndarray:
    """Ustten cekilmis urun fotografi (Etsy tarzi flatlay).

    Flatlay sahnesi genelde urunle AYNI RENKTE objelerle dolu: krem
    tisort + krem dantel + krem carsaf + krem tote bag. Referans
    fotografta dantel BGR[163,177,199], tisort BGR[175,191,209] --
    neredeyse ayirt edilemez.

    ONCEKI SURUM (Lab tohum genisletme) BU YUZDEN BASARISIZDI:
    maske sag ustteki danteli giysi sandi, x=1094'e kadar uzadi
    (kadraj 1152). Bu asimetri govde eksenini -37.6 dereceye cekti;
    gercek aci ~-13. Sonucta baski tisortun disina, arka plana dustu.

    Morfolojik acma denendi, dantel tisorte bitisik oldugu icin
    ayrilmadi (3 iterasyonda bile tek bilesen).

    SIMDIKI YONTEM: GrabCut.
      1. Lab tohum genisletme ile kaba bir bolge bul
      2. O bolgenin siniri GrabCut'a baslangic dikdortgeni olur
      3. GrabCut renk dagilimini iteratif ayirir -- yakin renkleri
         ayirmakta esik tabanli yontemden cok daha iyi

    Referans fotografta sonuc: kutusu x 136-1094 -> x 230-929,
    kadraj kenarina degme 77 px -> 0, govde acisi -37.6 -> -13.3.
    """
    h, w = bgr.shape[:2]
    smooth = cv2.bilateralFilter(bgr, 9, 75, 75)
    lab = cv2.cvtColor(smooth, cv2.COLOR_BGR2LAB).astype(np.float32)

    ph, pw = max(20, h // 12), max(20, w // 12)
    patch = lab[h // 2 - ph:h // 2 + ph, w // 2 - pw:w // 2 + pw].reshape(-1, 3)
    ref = np.median(patch, axis=0)

    k9 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    d = np.linalg.norm(lab - ref, axis=2)
    seed = (d < 8.0).astype(np.uint8)
    seed = cv2.morphologyEx(seed, cv2.MORPH_OPEN, k9)
    seed = cv2.morphologyEx(seed, cv2.MORPH_CLOSE, k9, iterations=2)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(seed)
    if n < 2:
        return np.zeros((h, w), np.uint8)
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    core = labels == biggest

    ys, xs = np.where(core)
    # Baslangic dikdortgeni: kaba bolgenin sinirini biraz iceri cek.
    # GrabCut disini kesin arka plan sayar, o yuzden fazla genis
    # verirsek dantel yine iceri girer.
    pad_x = int((xs.max() - xs.min()) * 0.04)
    pad_y = int((ys.max() - ys.min()) * 0.04)
    x0 = max(1, int(xs.min()) + pad_x)
    y0 = max(1, int(ys.min()) + pad_y)
    x1 = min(w - 2, int(xs.max()) - pad_x)
    y1 = min(h - 2, int(ys.max()) - pad_y)
    rect = (x0, y0, max(10, x1 - x0), max(10, y1 - y0))

    gc = np.zeros((h, w), np.uint8)
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(bgr, gc, rect, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        # GrabCut basarisiz olursa kaba bolgeye don -- hic maske
        # uretmemekten iyidir, ama kullanici uyarilmali.
        if debug is not None:
            debug["grabcut_failed"] = True
        return fill_holes(largest_component((core.astype(np.uint8)) * 255))

    mask = np.where((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    k15 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k15, iterations=2)
    mask = largest_component(mask)
    mask = fill_holes(mask)

    if debug is not None:
        debug["seed_rect"] = rect
        debug["core_coverage"] = float(core.mean() * 100)

    return mask


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
    p.add_argument("--method", choices=["classic", "cloth", "flatlay", "auto"],
                   default="classic",
                   help="auto: classic -> cloth -> flatlay sirasiyla dener")
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

    def run(method: str) -> np.ndarray:
        if method == "cloth":
            return cloth_mask(work)
        if method == "flatlay":
            return flatlay_mask(work, debug)
        return classic_mask(work, args.s_max, args.v_min, args.tolerance, debug)

    def coverage_of(m: np.ndarray) -> float:
        return float((m > 127).sum()) / m.size * 100

    used = args.method
    if args.method == "auto":
        # Sira: classic -> cloth -> flatlay. Ilk kabul edilebilir kaplamayi
        # veren yontem kazanir. Human fotograflarinda classic veya cloth
        # zaten basarili oldugu icin flatlay'e hic inilmiyor -- mevcut
        # davranis degismiyor.
        used = None
        for candidate in ("classic", "cloth", "flatlay"):
            try:
                trial = run(candidate)
            except SystemExit as err:
                print(f"  {candidate}: atlandi ({err})")
                continue
            cov = coverage_of(trial)
            ok = COVERAGE_MIN < cov < COVERAGE_MAX
            print(f"  {candidate:<8} kaplama %{cov:.1f}  "
                  f"{'kabul' if ok else 'yetersiz'}")
            if ok:
                mask, used = trial, candidate
                break
        if used is None:
            print("\nHATA: hicbir yontem kabul edilebilir maske uretemedi.",
                  file=sys.stderr)
            print("Fotografi kontrol et veya esikleri elle ayarla.", file=sys.stderr)
            return 1
    else:
        mask = run(args.method)

    # Tam çözünürlüğe geri büyüt, kenarı temizle
    if scale < 1.0:
        mask = cv2.resize(mask, (fw, fh), interpolation=cv2.INTER_LINEAR)
    mask = np.where(cv2.GaussianBlur(mask, (0, 0), 2) > 127, 255, 0).astype(np.uint8)

    coverage = float((mask > 127).sum()) / (fh * fw) * 100
    cv2.imwrite(str(out_path), mask)

    print(f"\n{args.model_id}  ({fw}x{fh})")
    print(f"  yöntem            : {used}"
          f"{'  (auto ile secildi)' if args.method == 'auto' else ''}")
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
