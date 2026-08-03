"""Tasarim dosyasindan mockup dosyasina giden ust seviye akis.

CLI ve (ileride) API ayni bu fonksiyonu cagirir. Is mantigi burada degil,
compositor.py icinde -- burasi yalnizca yukleme, cagirma, kaydetme.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

# Sunucu bu bayrakla pipeline'in guncel olup olmadigini anliyor.
# Quad override (offset_x/offset_y/rotate) BURADA uygulaniyor; server.py
# yeni ama pipeline.py eskiyse istek sessizce yok sayiliyordu.
QUAD_OVERRIDE_SUPPORTED = True

from .compositor import CompositeSettings, render
from .library import BaseModel, LibraryError, load_model
from .recolor import recolor_garment


def load_design(path: Path) -> np.ndarray:
    """Tasarimi RGBA float32 [0,1] olarak yukler.

    IMREAD_UNCHANGED, PNG'nin alfa kanalini korur -- baski tasarimlarinin
    neredeyse tamami seffaf arka planli oldugu icin bu sart.
    """
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(f"Tasarim okunamadi: {path}")

    if img.ndim == 2:  # gri tonlama
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:  # alfasiz
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)

    return img.astype(np.float32) / 255.0


def _merge_overrides(meta: dict, overrides: dict | None) -> dict:
    """CLI ayarlarini meta.json uzerine biner.

    Ic ice sozlukler (displacement, shading) tamamen degistirilmez,
    yalnizca verilen anahtarlar guncellenir -- yoksa --displace 18
    demek 'blur' ve 'mode' degerlerini de silerdi.
    """
    merged = {k: (dict(v) if isinstance(v, dict) else v) for k, v in meta.items()}

    for key, value in (overrides or {}).items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value

    return merged


def _print_mask_for_quad(garment_mask: np.ndarray, quad: np.ndarray,
                         inset: float = 0.004, feather: float = 0.004) -> np.ndarray:
    """Verilen quad icin baski maskesi uretir: quad AND giysi.

    print_mask.png diskte SABIT bir quad'dan turetiliyor. Arayuz
    tasarimi suruklediginde quad degisiyor ama maske degismedigi icin
    tasarim eski baski alaninin sinirinda KIRPILIYORDU: olculen kayma
    100.8 px yerine 68 px cikiyordu.

    Quad override edildiginde maskeyi de yeniden uretiyoruz. Override
    yoksa diskteki maske aynen kullanilir ve davranis degismez.

    inset/feather oranlari prepare_base.py ile ayni mantikta:
    goruntu yuksekliginin orani.
    """
    h, w = garment_mask.shape[:2]
    area = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(area, [quad.astype(np.int32)], 255)

    mask = cv2.bitwise_and(area, np.where(garment_mask > 127, 255, 0).astype(np.uint8))

    inset_px = int(round(max(1.0, h * inset)))
    if inset_px > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                      (inset_px * 2 + 1, inset_px * 2 + 1))
        mask = cv2.erode(mask, k)

    return cv2.GaussianBlur(mask, (0, 0), max(1.0, h * feather))


def generate_mockup(
    design_path: Path,
    model_id: str,
    library_dir: Path,
    output_path: Path,
    overrides: dict | None = None,
    color: str | None = None,
) -> Path:
    """Tek tasarim + tek base model -> tek mockup dosyasi.

    overrides: meta.json'daki ayarlari CLI'dan gecici olarak ezmek icin.
    color: preset adi veya '#RRGGBB'. None ise renk degistirilmez ve
           davranis eskisiyle BIREBIR ayni kalir -- mevcut testler ve
           kalibre edilmis meta.json degerleri etkilenmez.
    """
    model: BaseModel = load_model(model_id, library_dir)
    design = load_design(design_path)

    meta = _merge_overrides(model.meta, overrides)
    settings = CompositeSettings.from_meta(meta)

    # Renk degistirme, tasarim hattina girmeden ONCE base uzerinde yapilir.
    # compositor.py bundan habersiz; shading.png yeniden hesaplanmaz cunku
    # baski uzerindeki GORELI isik degismiyor.
    base_rgb = model.base.astype(np.float32) / 255.0
    if color:
        base_rgb, _ = recolor_garment(base_rgb, model.garment_mask, color)

    # Quad overrides ile ezilebilir: arayuz tasarimi surukleyip
    # dondururken meta.json'a yazmadan gecici bir quad gonderiyor.
    override_quad = overrides.get("print_quad") if overrides else None
    if override_quad:
        quad = np.array(override_quad, dtype=np.float32)
        # Maskeyi de yeni quad'a gore uret, yoksa eski sinirda kirpilir.
        print_mask = _print_mask_for_quad(model.garment_mask, quad)
    else:
        quad = model.print_quad
        print_mask = model.print_mask

    result = render(
        base_rgb=base_rgb,
        design_rgba=design,
        print_mask=print_mask,
        displace_gray=model.displace,
        shading_gray=model.shading,
        quad=quad,
        settings=settings,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # float32 [0,1] -> uint8, tek seferde ve en sonda.
    cv2.imwrite(str(output_path), np.clip(result * 255.0, 0, 255).astype(np.uint8))

    return output_path


__all__ = ["generate_mockup", "load_design", "LibraryError"]
