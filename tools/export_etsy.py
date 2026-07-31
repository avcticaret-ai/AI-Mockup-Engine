#!/usr/bin/env python3
"""Mockup'ları Etsy listeleme formatına çevirir.

    python tools/export_etsy.py outputs/batch/20260730-173455
    python tools/export_etsy.py <klasör> --shape square --format jpg
    python tools/export_etsy.py <klasör> --shape portrait   # 4:5

Etsy gereksinimleri (2026)
    en az 2000 piksel kısa kenar   (altındaysa zoom devre dışı kalır)
    1:1 kare veya 4:5 dikey
    sRGB renk profili
    JPG / PNG

ÇÖZÜNÜRLÜK UYARISI
    Kaynak görsel 2000 pikselin altındaysa bu araç büyütür ve UYARIR.
    Büyütme yumuşaklık yaratır. Doğru çözüm burada büyütmek değil,
    BASE ASSET'i baştan yeterli çözünürlükte üretmektir -- çünkü
    tasarım base çözünürlüğünde compose ediliyor, sonradan büyütmek
    tasarımın detayını geri getirmez.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

ETSY_MIN_SHORT_SIDE = 2000
SHAPES = {
    "square": (1, 1),        # 2000 x 2000
    "portrait": (4, 5),      # 2000 x 2500  -- arama küçük resmi bu oranı kullanıyor
    "landscape": (4, 3),     # 2666 x 2000
    "keep": None,            # oranı koru, yalnızca büyüt
}


def sample_background(bgr: np.ndarray) -> tuple[int, int, int]:
    """Dolgu rengini kenar bandından örnekler.

    Sabit beyaz dolgu, sıcak tonlu bir sahnede göze batan bir çerçeve
    yaratıyor. Kenarın medyanı sahneyle uyumlu kalıyor.
    """
    h, w = bgr.shape[:2]
    band = max(2, int(min(h, w) * 0.02))
    edges = np.concatenate([
        bgr[:band].reshape(-1, 3), bgr[-band:].reshape(-1, 3),
        bgr[:, :band].reshape(-1, 3), bgr[:, -band:].reshape(-1, 3),
    ])
    return tuple(int(v) for v in np.median(edges, axis=0))


def fit_to_shape(bgr: np.ndarray, ratio: tuple[int, int] | None,
                 min_short: int) -> tuple[np.ndarray, float]:
    """Hedef orana oturtur ve kısa kenarı min_short'a çıkarır.

    Kırpma YAPMIYOR -- mockup'ın kenarını kesmek modeli/giysiyi
    budayabilir. Bunun yerine fon rengiyle dolgu yapılıyor.
    """
    h, w = bgr.shape[:2]

    if ratio is None:
        target_w, target_h = w, h
    else:
        rw, rh = ratio
        if w / h > rw / rh:
            target_w, target_h = w, int(round(w * rh / rw))
        else:
            target_h, target_w = h, int(round(h * rw / rh))

    scale = max(1.0, min_short / min(target_w, target_h))
    out_w, out_h = int(round(target_w * scale)), int(round(target_h * scale))

    content_scale = min(out_w / w, out_h / h)
    new_w, new_h = int(round(w * content_scale)), int(round(h * content_scale))
    interp = cv2.INTER_LANCZOS4 if content_scale > 1 else cv2.INTER_AREA
    resized = cv2.resize(bgr, (new_w, new_h), interpolation=interp)

    canvas = np.full((out_h, out_w, 3), sample_background(bgr), dtype=np.uint8)
    y0, x0 = (out_h - new_h) // 2, (out_w - new_w) // 2
    canvas[y0:y0 + new_h, x0:x0 + new_w] = resized

    return canvas, content_scale


def save_srgb(bgr: np.ndarray, path: Path, fmt: str, max_kb: int) -> int:
    """sRGB profiliyle kaydeder.

    OpenCV renk profili yazmıyor. Profilsiz dosyalar bazı tarayıcılarda
    farklı renkte görünüyor; Etsy'de bu, gelen ürünün fotoğraftan farklı
    renkte olduğu şikayetine dönüşebiliyor.
    """
    img = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))

    if fmt == "png":
        img.save(path, format="PNG", optimize=True)
        return path.stat().st_size // 1024

    # JPG: boyut bütçesine oturana kadar kaliteyi düşür.
    for quality in (95, 92, 88, 84, 80, 75):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, subsampling=0,
                 optimize=True, progressive=True)
        if buf.tell() // 1024 <= max_kb or quality == 75:
            path.write_bytes(buf.getvalue())
            return buf.tell() // 1024
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source", help="mockup klasörü (batch çıktısı olabilir)")
    p.add_argument("--out", help="çıktı klasörü (varsayılan <source>/etsy)")
    p.add_argument("--shape", choices=list(SHAPES), default="square")
    p.add_argument("--format", choices=["jpg", "png"], default="jpg")
    p.add_argument("--min-side", type=int, default=ETSY_MIN_SHORT_SIDE)
    p.add_argument("--max-kb", type=int, default=1800,
                   help="JPG boyut bütçesi (kaynaklar 1MB-10MB arası çelişiyor, "
                        "güvenli taraf seçildi)")
    args = p.parse_args()

    src = Path(args.source)
    if not src.is_dir():
        print(f"HATA: klasör yok: {src}", file=sys.stderr)
        return 1

    images = sorted(f for f in src.rglob("*.png")
                    if not f.name.startswith("_") and "etsy" not in f.parts)
    if not images:
        print(f"HATA: {src} içinde .png yok", file=sys.stderr)
        return 1

    out_dir = Path(args.out) if args.out else src / "etsy"
    out_dir.mkdir(parents=True, exist_ok=True)

    ratio = SHAPES[args.shape]
    print(f"\nKaynak  : {src}  ({len(images)} görsel)")
    print(f"Biçim   : {args.shape}  {args.format.upper()}  "
          f"kısa kenar >= {args.min_side}px  sRGB")
    print(f"Çıktı   : {out_dir}\n")

    upscaled: list[tuple[str, float]] = []
    records = []

    for img_path in images:
        bgr = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
        if bgr is None:
            print(f"  atlandı (okunamadı): {img_path.name}", file=sys.stderr)
            continue

        src_h, src_w = bgr.shape[:2]
        fitted, content_scale = fit_to_shape(bgr, ratio, args.min_side)
        out_path = out_dir / f"{img_path.stem}.{args.format}"
        kb = save_srgb(fitted, out_path, args.format, args.max_kb)

        out_h, out_w = fitted.shape[:2]
        flag = ""
        if content_scale > 1.05:
            upscaled.append((img_path.name, content_scale))
            flag = f"  <- %{(content_scale - 1) * 100:.0f} BÜYÜTÜLDÜ"

        print(f"  {img_path.stem:<38} {src_w}x{src_h} -> {out_w}x{out_h}  "
              f"{kb} KB{flag}")

        records.append({
            "source": img_path.name,
            "output": out_path.name,
            "source_size": [src_w, src_h],
            "output_size": [out_w, out_h],
            "upscale_factor": round(content_scale, 3),
            "kb": kb,
        })

    (out_dir / "etsy_manifest.json").write_text(
        json.dumps({"shape": args.shape, "format": args.format,
                    "min_side": args.min_side, "images": records},
                   indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{len(records)} görsel hazır -> {out_dir}")

    if upscaled:
        worst = max(f for _, f in upscaled)
        print(f"\n{'=' * 64}")
        print(f"UYARI: {len(upscaled)} görsel büyütüldü (en fazla %{(worst-1)*100:.0f}).")
        print("Büyütme yumuşaklık yaratır ve Etsy bulanık görsellerde zoom'u")
        print("devre dışı bırakır.")
        print()
        print("Doğru çözüm burada değil, base asset tarafında:")
        need = int(np.ceil(args.min_side / min(
            r["source_size"] for r in records if r["upscale_factor"] > 1.05)[0] * 1000) / 1000 * 100)
        print(f"  comfybridge/variants.json içinde width/height değerlerini")
        print(f"  yaklaşık %{need - 100} artır, VEYA base.png'yi kütüphaneye")
        print(f"  eklemeden önce bir upscaler ile büyüt.")
        print()
        print("Tasarım base çözünürlüğünde compose ediliyor; mockup'ı sonradan")
        print("büyütmek tasarımın kaybolan detayını geri getirmez.")
        print("=" * 64)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
