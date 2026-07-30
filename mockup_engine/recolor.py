"""Giysi rengi degistirme.

Compositor'dan TAMAMEN AYRI. Bu modul base.png uzerinde on islem yapar;
tasarim hattina (warp -> displace -> shade -> mask -> composite) hic
karismaz. compositor.py'ye dokunulmadi, regresyon testleri etkilenmedi.

    base.png --recolor--> renkli base --compositor--> mockup

Neden CIELAB
------------
Ilk tasarimda difuz/spekuler ayrimi + linear uzayda carpma planlanmisti.
Uygulamadan once sayisal olarak kontrol edildi ve YETERSIZ cikti:

    beyaz base L* yayilimi        : ~21.5
    linear carpma ile siyah       : ~2.8    (%13)
    esik (beyazin %60'i)          : 12.9

Sebep, gamma'nin yonu. Linear uzayda carpma, koyu hedefte kivrim
bilgisini sifira dogru sikistiriyor; sRGB'ye geri donusteki gamma
genislemesi bunu telafi etmeye yetmiyor.

Bu yuzden yontem CIELAB'da KONTRAST KORUMAYA cevrildi:

    L*_cikti = L*_hedef + (L*_base - L*_ortalama) * kontrast

L* algisal olarak duzgun oldugu icin ayni L* yayilimi koyu ve acik
renkte ayni miktarda "kivrim gorunurlugu" demek. Ayrica cv2'nin Lab
donusumu sRGB -> linear -> XYZ -> Lab zincirini kendisi yapiyor; yani
istenen linear workflow bedava geliyor, elle gamma yonetimi gerekmiyor.

Karsilastirma icin naif yontem de `method="multiply"` olarak duruyor --
tools/verify_recolor.py ikisini yan yana olcuyor.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


# --------------------------------------------------------------------------
# Renk presetleri
# --------------------------------------------------------------------------
# Gercek kumas degerleri, saf renkler DEGIL.
# Saf #000000 difuz terimi sifirlar; gercek siyah tisort ~#1F1F1F.
# Beyaz kumas da asla 255 degildir.

COLOR_PRESETS: dict[str, str] = {
    "white": "#F7F7F5",
    "buttery": "#EFDFA8",       # Bella Canvas "Butter"
    "light_green": "#9CAF88",   # sage
    "black": "#1F1F1F",
    "navy": "#232F3E",
}

# Koyu hedeflerde kontrasti bir miktar kismak gercege daha yakin:
# gercek siyah tisortun L* yayilimi beyazinkinden dusuktur.
DEFAULT_CONTRAST: dict[str, float] = {
    "black": 0.85,
    "navy": 0.90,
}


@dataclass
class RecolorSettings:
    """Renk degistirme parametreleri."""

    # L* yayiliminin ne kadari korunacak. 1.0 = birebir.
    contrast: float = 1.0

    # Spekuler bolgede renk doygunlugunun ne kadari kaybolacak.
    # Gercek kumasta parlamalar beyaza doner; 0 = donmez, 1 = tamamen notr.
    spec_desaturate: float = 0.45

    # Spekuler kabul edilen normalize L* esigi (0-1, giysi araligi icinde).
    spec_knee: float = 0.72

    # Maske kenari yumusatma (piksel). Sert kenar dikis izi gibi gorunur.
    edge_feather: float = 2.0

    # L* alt siniri. 0'a kirpmak yerine kucuk bir taban birakiyoruz.
    l_floor: float = 1.0

    # Kirpma olacaksa hedef L*'i kaydirip YAYILIMI koru.
    # Kivrim gorunurlugu, hedef parlakligi birebir tutmaktan onemli:
    # beyaz base uzerine beyaz uygularken hedef L*=97, base ortalamasi
    # 85 -- fark tavana dayanip giysinin ucte birini duzlestiriyor.
    preserve_spread: bool = True

    # Izin verilen kirpma butcesi (giysi pikselinin yuzdesi).
    clip_budget: float = 2.0


# --------------------------------------------------------------------------
# Yardimcilar
# --------------------------------------------------------------------------

def hex_to_bgr01(hex_color: str) -> np.ndarray:
    """'#1F1F1F' -> float32 BGR [0,1]"""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"Gecersiz renk: {hex_color}")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return np.array([b, g, r], dtype=np.float32)


def resolve_color(name_or_hex: str) -> np.ndarray:
    """Preset adi veya hex kodunu BGR [0,1] olarak dondurur."""
    key = name_or_hex.strip().lower()
    if key in COLOR_PRESETS:
        return hex_to_bgr01(COLOR_PRESETS[key])
    if key.startswith("#"):
        return hex_to_bgr01(key)
    raise ValueError(
        f"Bilinmeyen renk: {name_or_hex}. "
        f"Presetler: {', '.join(COLOR_PRESETS)} veya #RRGGBB"
    )


def default_contrast(name_or_hex: str) -> float:
    return DEFAULT_CONTRAST.get(name_or_hex.strip().lower(), 1.0)


def bgr_to_lab(bgr01: np.ndarray) -> np.ndarray:
    """float32 BGR [0,1] -> Lab (L 0-100, a/b -127..127).

    cv2 bu donusumde sRGB gamma'sini kendisi cozuyor, yani hesap
    fiziksel olarak dogru linear XYZ uzerinden gidiyor.
    """
    return cv2.cvtColor(bgr01.astype(np.float32), cv2.COLOR_BGR2Lab)


def lab_to_bgr(lab: np.ndarray) -> np.ndarray:
    out = cv2.cvtColor(lab.astype(np.float32), cv2.COLOR_Lab2BGR)
    return np.clip(out, 0.0, 1.0)


def color_lab(bgr01: np.ndarray) -> tuple[float, float, float]:
    """Tek bir rengin Lab degeri."""
    patch = bgr01.reshape(1, 1, 3).astype(np.float32)
    lab = bgr_to_lab(patch)[0, 0]
    return float(lab[0]), float(lab[1]), float(lab[2])


def _mask01(garment_mask: np.ndarray, feather: float) -> np.ndarray:
    m = garment_mask.astype(np.float32) / 255.0
    if feather > 0:
        m = cv2.GaussianBlur(m, (0, 0), feather)
    return np.clip(m, 0.0, 1.0)


# --------------------------------------------------------------------------
# Ana fonksiyon
# --------------------------------------------------------------------------

def recolor_garment(
    base_bgr01: np.ndarray,
    garment_mask: np.ndarray,
    color: str,
    settings: RecolorSettings | None = None,
    method: str = "lab",
) -> tuple[np.ndarray, dict]:
    """Giysi bolgesinin rengini degistirir.

    base_bgr01 : H x W x 3, float32 [0,1], sRGB kodlu
    garment_mask : H x W, uint8 (255 = giysi)
    color : preset adi veya '#RRGGBB'
    method : "lab" (onerilen) | "multiply" (karsilastirma icin naif)

    Doner: (renkli_base, olcum_sozlugu)
    """
    if settings is None:
        settings = RecolorSettings(contrast=default_contrast(color))

    if base_bgr01.shape[:2] != garment_mask.shape[:2]:
        raise ValueError(
            f"garment_mask boyutu base ile uyusmuyor: "
            f"{garment_mask.shape[:2]} vs {base_bgr01.shape[:2]}"
        )

    target = resolve_color(color)
    inside = garment_mask > 127

    if not inside.any():
        raise ValueError("garment_mask bos -- renk degistirilecek bolge yok.")

    if method == "multiply":
        recolored, stats = _recolor_multiply(base_bgr01, inside, target)
    elif method == "lab":
        recolored, stats = _recolor_lab(base_bgr01, inside, target, settings)
    else:
        raise ValueError(f"Bilinmeyen method: {method}")

    # Yalnizca giysi bolgesine uygula, kenari yumusat.
    m = _mask01(garment_mask, settings.edge_feather)[..., None]
    out = base_bgr01 * (1.0 - m) + recolored * m

    stats["method"] = method
    stats["color"] = color
    stats["contrast"] = settings.contrast
    return np.clip(out, 0.0, 1.0), stats


def _recolor_lab(
    base_bgr01: np.ndarray,
    inside: np.ndarray,
    target: np.ndarray,
    s: RecolorSettings,
) -> tuple[np.ndarray, dict]:
    """CIELAB kontrast koruma."""
    lab = bgr_to_lab(base_bgr01)
    L = lab[..., 0]

    L_in = L[inside]
    L_mean = float(L_in.mean())
    L_lo, L_hi = float(np.percentile(L_in, 2)), float(np.percentile(L_in, 98))

    Lt, at, bt = color_lab(target)
    Lt_requested = Lt

    # 1. L*: hedefin cevresine, base'in yayilimini koruyarak yerlestir.
    #    Kirpma butcesi asilacaksa hedefi kaydir -- yayilim daha degerli.
    if s.preserve_spread:
        lo_q, hi_q = np.percentile(L_in, [s.clip_budget, 100.0 - s.clip_budget])
        head = (hi_q - L_mean) * s.contrast     # ortalamanin ustundeki pay
        tail = (L_mean - lo_q) * s.contrast     # altindaki pay
        Lt = min(Lt, 100.0 - head)
        Lt = max(Lt, s.l_floor + tail)

    L_out = Lt + (L - L_mean) * s.contrast

    # Hem taban hem TAVAN kirpmasi olculuyor. Tavani atlamak yaniltici:
    # base'ten daha acik bir hedefe giderken (or. beyaz base -> beyaz)
    # parlak kivrimlar L*=100'u asip beyaza yapisiyor ve yayilim
    # sessizce daraliyor.
    clip_low = float((L_out[inside] < s.l_floor).mean() * 100.0)
    clip_high = float((L_out[inside] > 100.0).mean() * 100.0)
    L_out = np.clip(L_out, s.l_floor, 100.0)

    # 2. Kroma: hedeften al, spekuler bolgede notre dogru soldur
    span = max(L_hi - L_lo, 1e-6)
    L_norm = np.clip((L - L_lo) / span, 0.0, 1.0)
    spec = np.clip((L_norm - s.spec_knee) / max(1.0 - s.spec_knee, 1e-6), 0.0, 1.0)
    keep = 1.0 - spec * s.spec_desaturate

    out_lab = np.stack([L_out, at * keep, bt * keep], axis=-1)

    return lab_to_bgr(out_lab), {
        "target_L": Lt,
        "target_L_requested": Lt_requested,
        "L_shifted": abs(Lt - Lt_requested) > 0.05,
        "base_L_mean": L_mean,
        "clip_low": clip_low,
        "clip_high": clip_high,
    }


def _recolor_multiply(
    base_bgr01: np.ndarray,
    inside: np.ndarray,
    target: np.ndarray,
) -> tuple[np.ndarray, dict]:
    """Naif yontem: linear uzayda hedef renkle carpma.

    Yalnizca KARSILASTIRMA icin duruyor. Koyu hedeflerde kivrim
    bilgisini sikistiriyor; verify_recolor.py bunu sayisal olarak
    gosteriyor. Uretimde kullanma.
    """
    lin = np.where(base_bgr01 <= 0.04045,
                   base_bgr01 / 12.92,
                   ((base_bgr01 + 0.055) / 1.055) ** 2.4)

    # Rec.709 linear luminance
    Y = lin[..., 2] * 0.2126 + lin[..., 1] * 0.7152 + lin[..., 0] * 0.0722
    Y_mean = float(Y[inside].mean()) or 1e-6
    ratio = (Y / Y_mean)[..., None]

    tgt_lin = np.where(target <= 0.04045,
                       target / 12.92,
                       ((target + 0.055) / 1.055) ** 2.4)

    out_lin = np.clip(tgt_lin * ratio, 0.0, 1.0)

    out = np.where(out_lin <= 0.0031308,
                   out_lin * 12.92,
                   1.055 * np.power(out_lin, 1 / 2.4) - 0.055)

    Lt, _, _ = color_lab(target)
    return np.clip(out, 0.0, 1.0), {
        "target_L": Lt,
        "target_L_requested": Lt,
        "L_shifted": False,
        "base_L_mean": float("nan"),
        "clip_low": 0.0,
        "clip_high": float((out_lin[inside] >= 1.0).mean() * 100.0),
    }


# --------------------------------------------------------------------------
# Olcum
# --------------------------------------------------------------------------

def lightness_spread(bgr01: np.ndarray, garment_mask: np.ndarray) -> dict:
    """Giysi bolgesindeki L* yayilimi.

    Kivrim gorunurlugunun algisal olcusu. sRGB seviye sayisi yaniltici
    oldugu icin (gamma), olcum CIELAB L* uzerinde yapiliyor.
    """
    L = bgr_to_lab(bgr01)[..., 0]
    vals = L[garment_mask > 127]
    p5, p95 = np.percentile(vals, [5, 95])
    return {
        "L_mean": float(vals.mean()),
        "L_std": float(vals.std()),
        "L_p5": float(p5),
        "L_p95": float(p95),
        "L_span": float(p95 - p5),
    }


__all__ = [
    "COLOR_PRESETS",
    "RecolorSettings",
    "recolor_garment",
    "lightness_spread",
    "resolve_color",
    "default_contrast",
    "hex_to_bgr01",
]
