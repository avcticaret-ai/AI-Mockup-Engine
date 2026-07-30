"""Tasarim dosyasindan mockup dosyasina giden ust seviye akis.

CLI ve (ileride) API ayni bu fonksiyonu cagirir. Is mantigi burada degil,
compositor.py icinde -- burasi yalnizca yukleme, cagirma, kaydetme.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .compositor import CompositeSettings, render
from .library import BaseModel, LibraryError, load_model


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


def generate_mockup(
    design_path: Path,
    model_id: str,
    library_dir: Path,
    output_path: Path,
    overrides: dict | None = None,
) -> Path:
    """Tek tasarim + tek base model -> tek mockup dosyasi.

    overrides: meta.json'daki ayarlari CLI'dan gecici olarak ezmek icin.
    """
    model: BaseModel = load_model(model_id, library_dir)
    design = load_design(design_path)

    meta = _merge_overrides(model.meta, overrides)
    settings = CompositeSettings.from_meta(meta)

    result = render(
        base_rgb=model.base.astype(np.float32) / 255.0,
        design_rgba=design,
        print_mask=model.print_mask,
        displace_gray=model.displace,
        shading_gray=model.shading,
        quad=model.print_quad,
        settings=settings,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # float32 [0,1] -> uint8, tek seferde ve en sonda.
    cv2.imwrite(str(output_path), np.clip(result * 255.0, 0, 255).astype(np.uint8))

    return output_path


__all__ = ["generate_mockup", "load_design", "LibraryError"]
