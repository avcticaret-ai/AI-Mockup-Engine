#!/usr/bin/env python3
"""base.png üzerinde baskı alanının 4 köşesini işaretler ve meta.json yazar.

    python tools/calibrate_quad.py bella-canvas-3001/female-front-001

Bir pencere açılır. Göğüsteki baskı alanının köşelerine ŞU SIRAYLA tıkla:

    1. sol-üst    2. sağ-üst    3. sağ-alt    4. sol-alt

Tuşlar:  u = son noktayı geri al    r = sıfırla    s = kaydet    q = çık

Sunucuda / GUI olmayan makinede çalıştırıyorsan --points ile elle ver:

    python tools/calibrate_quad.py <model> --points 488,486 912,486 922,1064 478,1064

Bu araç meta.json yoksa şablonu da oluşturur -- köken alanları
(source, publishable) dahil. Bunları sonradan doldurmak neredeyse
imkânsız, bu yüzden en baştan yazılıyor.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import cv2
import numpy as np

ENGINE = Path(__file__).resolve().parent.parent
LIBRARY = ENGINE / "assets" / "base-library"

CORNER_NAMES = ("sol-üst", "sağ-üst", "sağ-alt", "sol-alt")
MAX_WINDOW_H = 900


def meta_template(model_id: str) -> dict:
    """Yeni bir base model için meta.json iskeleti.

    'source' ve 'publishable' alanları özellikle önemli: kütüphane 100
    modele çıktığında hangisinin AI üretimi hangisinin gerçek fotoğraf
    olduğunu ayırt edemezsen, Etsy'ye hangi görselleri koyabileceğini
    de bilemezsin.
    """
    parts = model_id.split("/")
    return {
        "id": model_id,
        "label": parts[-1],
        "brand": "",
        "model": "",
        "color": "",
        "gender": "",
        "pose": "",
        "environment": "",

        "source": "unknown",          # ai-generated | licensed | photographed
        "source_detail": "",
        "verified_garment": False,    # gerçekten bu marka/model mi
        "publishable": False,         # Etsy listelemesinde kullanılabilir mi
        "created": date.today().isoformat(),

        "print_quad": [],
        "design_scale": 0.9,
        "displacement": {"strength": 16.0, "blur": 9, "mode": "gradient"},
        "shading": {"strength": 0.85},
        "edge_feather": 0,
    }


def save(model_dir: Path, points: list[tuple[int, int]]) -> None:
    meta_path = model_dir / "meta.json"
    meta = (
        json.loads(meta_path.read_text(encoding="utf-8"))
        if meta_path.exists()
        else meta_template(model_dir.relative_to(LIBRARY).as_posix())
    )
    meta["print_quad"] = [[int(x), int(y)] for x, y in points]
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    print(f"\nprint_quad yazıldı -> {meta_path}")
    print("Sonraki adım: python tools/prepare_base.py "
          f"{model_dir.relative_to(LIBRARY).as_posix()}\n")


def pick_interactively(base: np.ndarray) -> list[tuple[int, int]] | None:
    h, w = base.shape[:2]
    scale = min(1.0, MAX_WINDOW_H / h)
    view_size = (int(w * scale), int(h * scale))

    points: list[tuple[int, int]] = []

    def on_mouse(event, x, y, flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 4:
            # Tıklama pencere koordinatında; orijinal çözünürlüğe geri çevir.
            points.append((int(round(x / scale)), int(round(y / scale))))

    window = "print_quad -- sol-ust, sag-ust, sag-alt, sol-alt"
    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_mouse)

    while True:
        view = cv2.resize(base, view_size)

        for i, (px, py) in enumerate(points):
            vp = (int(px * scale), int(py * scale))
            cv2.circle(view, vp, 6, (0, 0, 255), -1)
            cv2.putText(view, str(i + 1), (vp[0] + 10, vp[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        if len(points) >= 2:
            pts = np.array([(int(x * scale), int(y * scale)) for x, y in points])
            cv2.polylines(view, [pts], len(points) == 4, (0, 220, 0), 2)

        hint = (CORNER_NAMES[len(points)] + " noktasina tikla"
                if len(points) < 4 else "s = kaydet   u = geri al   r = sifirla")
        cv2.putText(view, hint, (14, 28), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (255, 255, 255), 3)
        cv2.putText(view, hint, (14, 28), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (0, 0, 0), 1)

        cv2.imshow(window, view)
        key = cv2.waitKey(20) & 0xFF

        if key == ord("q"):
            cv2.destroyAllWindows()
            return None
        if key == ord("u") and points:
            points.pop()
        if key == ord("r"):
            points.clear()
        if key == ord("s"):
            if len(points) != 4:
                print("4 nokta gerekli.")
                continue
            cv2.destroyAllWindows()
            return points


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("model_id", help="ör. bella-canvas-3001/female-front-001")
    p.add_argument("--library", default=str(LIBRARY))
    p.add_argument("--points", nargs=4, metavar="X,Y",
                   help="GUI yerine 4 noktayı elle ver")
    args = p.parse_args()

    model_dir = Path(args.library) / args.model_id
    base_path = model_dir / "base.png"

    if not base_path.exists():
        print(f"HATA: {base_path} yok.\n"
              f"Base görseli bu klasöre base.png olarak kaydet.", file=sys.stderr)
        return 1

    if args.points:
        try:
            points = [tuple(int(v) for v in pt.split(",")) for pt in args.points]
        except ValueError:
            print("HATA: --points formatı 'X,Y X,Y X,Y X,Y' olmalı.", file=sys.stderr)
            return 1
        save(model_dir, points)
        return 0

    base = cv2.imread(str(base_path), cv2.IMREAD_COLOR)
    try:
        points = pick_interactively(base)
    except cv2.error:
        print("HATA: GUI penceresi açılamadı (başsız ortam?).\n"
              "--points ile koordinatları elle ver.", file=sys.stderr)
        return 1

    if points is None:
        print("İptal edildi.")
        return 1

    save(model_dir, points)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
