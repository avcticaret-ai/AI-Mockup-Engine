"""Base model kutuphanesinin okunmasi ve dogrulanmasi.

Bir base model, bir klasordur. Klasorde su dosyalar bulunur:

    base.png            mankenin bos tisort giydigi gorsel (RGB)
    garment_mask.png    tisortun tamami (gri tonlama, 255 = tisort)
    print_mask.png      baski alani (gri tonlama, 255 = baski)
    displace.png        kumas kivrim haritasi (gri tonlama)
    shading.png         isik/golge haritasi (gri tonlama, 128 = notr)
    meta.json           etiketler ve compositor parametreleri

Veritabani yok -- kutuphane dosya sisteminin kendisi. 30-50 model icin
fazlasiyla yeterli, SaaS'a gecilirse burasi degisir.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

REQUIRED_FILES = (
    "base.png",
    "garment_mask.png",
    "print_mask.png",
    "displace.png",
    "shading.png",
    "meta.json",
)


class LibraryError(Exception):
    """Kutuphane okuma/dogrulama hatasi."""


@dataclass
class BaseModel:
    """Diske yazilmis bir base modelin bellekteki hali."""

    id: str
    path: Path
    meta: dict

    base: np.ndarray = field(repr=False)          # H x W x 3, uint8, BGR
    garment_mask: np.ndarray = field(repr=False)  # H x W, uint8
    print_mask: np.ndarray = field(repr=False)    # H x W, uint8
    displace: np.ndarray = field(repr=False)      # H x W, uint8
    shading: np.ndarray = field(repr=False)       # H x W, uint8

    @property
    def size(self) -> tuple[int, int]:
        """(genislik, yukseklik)"""
        h, w = self.base.shape[:2]
        return w, h

    @property
    def print_quad(self) -> np.ndarray:
        """Baski alaninin 4 kosesi: sol-ust, sag-ust, sag-alt, sol-alt."""
        quad = self.meta.get("print_quad")
        if not quad or len(quad) != 4:
            raise LibraryError(
                f"{self.id}: meta.json icinde 4 noktali 'print_quad' yok."
            )
        return np.array(quad, dtype=np.float32)

    def label(self) -> str:
        return self.meta.get("label", self.id)


def _read_gray(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise LibraryError(f"Okunamadi: {path}")
    return img


def load_model(model_id: str, library_dir: Path) -> BaseModel:
    """Tek bir base modeli diskten yukler ve dogrular."""
    model_dir = library_dir / model_id

    if not model_dir.is_dir():
        available = ", ".join(list_models(library_dir))
        raise LibraryError(
            f"Base model bulunamadi: {model_id}\n"
            f"Kutuphanedeki modeller: {available or '(bos)'}"
        )

    missing = [f for f in REQUIRED_FILES if not (model_dir / f).exists()]
    if missing:
        raise LibraryError(
            f"{model_id}: eksik dosyalar -> {', '.join(missing)}"
        )

    base = cv2.imread(str(model_dir / "base.png"), cv2.IMREAD_COLOR)
    if base is None:
        raise LibraryError(f"{model_id}: base.png okunamadi.")

    model = BaseModel(
        id=model_id,
        path=model_dir,
        meta=json.loads((model_dir / "meta.json").read_text(encoding="utf-8")),
        base=base,
        garment_mask=_read_gray(model_dir / "garment_mask.png"),
        print_mask=_read_gray(model_dir / "print_mask.png"),
        displace=_read_gray(model_dir / "displace.png"),
        shading=_read_gray(model_dir / "shading.png"),
    )

    _validate_dimensions(model)
    return model


def _validate_dimensions(model: BaseModel) -> None:
    """Tum haritalar base.png ile ayni boyutta olmali.

    Bu kontrol olmazsa cv2.remap sessizce yanlis sonuc uretir -- hata
    vermez, sadece mockup bozuk cikar. Erken ve gurultulu patlamasi
    daha iyi.
    """
    h, w = model.base.shape[:2]
    for name in ("garment_mask", "print_mask", "displace", "shading"):
        layer = getattr(model, name)
        if layer.shape[:2] != (h, w):
            lh, lw = layer.shape[:2]
            raise LibraryError(
                f"{model.id}: {name}.png boyutu {lw}x{lh}, "
                f"base.png ise {w}x{h}. Hepsi ayni olmali."
            )


def list_models(library_dir: Path) -> list[str]:
    """Kutuphanedeki gecerli model id'leri.

    Ozyinelemeli tarar, cunku kutuphane marka/urun bazli ic ice
    gruplaniyor:

        bella-canvas-3001/female-front-001
        bella-canvas-3001/male-front-002
        gildan-5000/female-front-001

    Model id = base-library'ye gore GORELI YOL. Duz yerlesim de
    calismaya devam eder (or. "test-model"), boylece 100+ modele
    buyurken eski varliklar bozulmaz.
    """
    if not library_dir.is_dir():
        return []

    return sorted(
        meta.parent.relative_to(library_dir).as_posix()
        for meta in library_dir.rglob("meta.json")
    )
