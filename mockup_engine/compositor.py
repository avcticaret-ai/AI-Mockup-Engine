"""Compositor -- motorun kalbi.

Tasarimi base modelin baski alanina yerlestirir. Hicbir asamada uretken
model kullanilmaz: tasarimin pikselleri yalnizca geometrik olarak
donusturulur ve isiklandirilir, asla yeniden cizilmez. Yazi, logo ve ince
detay birebir korunur.

Islem sirasi:

    1. warp        tasarimi baski alaninin 4 kosesine oturt (perspektif)
    2. displace    kumas kivrimlarina gore piksel piksel kaydir
    3. shade       isik/golge haritasini uygula
    4. mask        baski alani disini kes
    5. composite   base gorselin uzerine bindir

Tum ara hesaplar float32 [0,1] uzerinde yapilir. uint8'e yalnizca en
sonda donulur -- ara adimlarda 8-bit'e yuvarlamak displacement'ta gorunur
bantlanma yaratir.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class CompositeSettings:
    """meta.json icindeki compositor parametrelerinin karsiligi."""

    # Tasarimin baski alani icindeki doluluk orani. 1.0 = alani tamamen
    # kaplar. Tisortte 0.85-0.95 daha dogal durur.
    #
    # 1.0 UZERI: tasarim baski alanini asar ve print_mask tarafindan
    # kirpilir. Teknik olarak calisir ama GERCEK baski alanini yanlis
    # gosterir -- print_quad gercek 12x16 incten turetildiyse 1.0 ustu
    # bir deger, basilamayacak bir mockup uretir.
    design_scale: float = 1.0

    # Displacement gucu (piksel). Kumas ne kadar kirisiksa o kadar dusuk.
    displace_strength: float = 12.0
    # Haritayi yumusatma yaricapi. Yuksek deger = genis, yumusak kivrimlar.
    displace_blur: int = 9
    # "gradient" = kivrim egimine gore kaydir (kumas icin dogru olan)
    # "value"    = Photoshop Displace filtresi gibi tek kanalli kaydirma
    displace_mode: str = "gradient"

    # Golge/isik siddeti. 0 = golge yok, 1 = harita birebir uygulanir.
    shading_strength: float = 0.85

    # Baski kenarlarini yumusatma (piksel). Maske zaten yumusaksa 0 birak.
    edge_feather: int = 0

    @classmethod
    def from_meta(cls, meta: dict) -> "CompositeSettings":
        disp = meta.get("displacement", {})
        shade = meta.get("shading", {})
        return cls(
            design_scale=float(meta.get("design_scale", 1.0)),
            displace_strength=float(disp.get("strength", 12.0)),
            displace_blur=int(disp.get("blur", 9)),
            displace_mode=str(disp.get("mode", "gradient")),
            shading_strength=float(shade.get("strength", 0.85)),
            edge_feather=int(meta.get("edge_feather", 0)),
        )


# --------------------------------------------------------------------------
# 1. Perspektif
# --------------------------------------------------------------------------

def _quad_dimensions(quad: np.ndarray) -> tuple[float, float]:
    """Perspektif quad'in ortalama genislik ve yuksekligi.

    Quad egik oldugu icin ust ve alt kenar farkli uzunlukta olabilir;
    ortalamalarini aliyoruz. Bu deger yalnizca kaynak tuvalin en-boy
    oranini belirlemek icin kullaniliyor.
    """
    tl, tr, br, bl = quad
    width = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2.0
    height = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2.0
    return float(width), float(height)


def _fit_contain(
    design: np.ndarray, canvas_w: int, canvas_h: int, scale: float
) -> np.ndarray:
    """Tasarimi en-boy oranini BOZMADAN tuvalin icine ortalar.

    Baski alani kare degilse ve tasarim direkt gerilirse logo ezilir.
    Bu yuzden 'contain' davranisi: tasarim tuvale sigar, artan yerler
    seffaf kalir.
    """
    dh, dw = design.shape[:2]
    factor = min(canvas_w / dw, canvas_h / dh) * scale

    new_w = max(1, int(round(dw * factor)))
    new_h = max(1, int(round(dh * factor)))

    # Kucultmede INTER_AREA, buyutmede INTER_CUBIC -- ince yazilarda fark eder.
    interp = cv2.INTER_AREA if factor < 1.0 else cv2.INTER_CUBIC
    resized = cv2.resize(design, (new_w, new_h), interpolation=interp)

    canvas = np.zeros((canvas_h, canvas_w, 4), dtype=design.dtype)
    x0 = (canvas_w - new_w) // 2
    y0 = (canvas_h - new_h) // 2

    # scale > 1.0 tasarimi tuvalden BUYUK yapar ve x0/y0 negatife duser.
    # numpy negatif dilim baslangicini "sondan" diye yorumluyor, bu da
    # yanlis sekle yazmaya calisip ValueError firlatiyordu:
    #   could not broadcast (651,651,4) into (37,109,4)
    # Tasan kismi kaynaktan kirpiyoruz; scale <= 1.0 yolunda hicbir sey
    # degismiyor cunku orada sx0/sy0 zaten 0.
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    cw = min(new_w - sx0, canvas_w - dx0)
    ch = min(new_h - sy0, canvas_h - dy0)

    if cw > 0 and ch > 0:
        canvas[dy0:dy0 + ch, dx0:dx0 + cw] = resized[sy0:sy0 + ch, sx0:sx0 + cw]

    return canvas


def warp_design(
    design_rgba: np.ndarray,
    quad: np.ndarray,
    canvas_size: tuple[int, int],
    scale: float = 1.0,
) -> np.ndarray:
    """Tasarimi baski alaninin 4 kosesine oturtur.

    design_rgba : H x W x 4, float32 [0,1]
    quad        : 4 x 2, [sol-ust, sag-ust, sag-alt, sol-alt]
    canvas_size : (genislik, yukseklik) -- base gorselin boyutu
    """
    canvas_w, canvas_h = canvas_size
    quad_w, quad_h = _quad_dimensions(quad)

    src_w = max(2, int(round(quad_w)))
    src_h = max(2, int(round(quad_h)))

    source = _fit_contain(design_rgba, src_w, src_h, scale)

    src_corners = np.array(
    [
    [0, 0],
    [src_w - 1, 0],
    [src_w - 1, src_h - 1],
    [0, src_h - 1],
    ],
    dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(src_corners, quad.astype(np.float32))

    warped = cv2.warpPerspective(
        source,
        matrix,
        (canvas_w, canvas_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )

    # INTER_CUBIC keskin kenarlarda tasma (ringing) yapar: siyah-beyaz
    # sinirinda deger 1.19'a cikip -0.19'a inebiliyor. Kirpmazsak bu
    # tasma sonraki adimlarda golgeleme ve alfa hesabini bozar, ciktida
    # yazi kenarlarinda hale olarak gorunur.
    return np.clip(warped, 0.0, 1.0)


# --------------------------------------------------------------------------
# 2. Displacement
# --------------------------------------------------------------------------

def build_displacement_maps(
    displace_gray: np.ndarray, settings: CompositeSettings
) -> tuple[np.ndarray, np.ndarray]:
    """cv2.remap icin map_x / map_y uretir.

    'gradient' modu kivrim haritasinin egimini kullanir: tasarim kumasin
    yukseldigi yerden alcaldigi yone dogru kayar. Kumas icin fiziksel
    olarak dogru olan bu.

    'value' modu Photoshop'un Displace filtresi gibi davranir: gri
    degerin kendisi hem x hem y'de ayni miktarda kaydirma yapar. Hazir
    PSD sablonlarindan gelen haritalarla uyum icin var.
    """
    h, w = displace_gray.shape[:2]

    field = displace_gray.astype(np.float32) / 255.0
    blur = settings.displace_blur
    if blur > 0:
        k = blur * 2 + 1  # GaussianBlur tek sayi cekirdek ister
        field = cv2.GaussianBlur(field, (k, k), 0)

    if settings.displace_mode == "value":
        offset = (field - 0.5) * 2.0
        dx = offset * settings.displace_strength
        dy = offset * settings.displace_strength
    else:
        gx = cv2.Sobel(field, cv2.CV_32F, 1, 0, ksize=5)
        gy = cv2.Sobel(field, cv2.CV_32F, 0, 1, ksize=5)

        # Sobel ciktisinin araligi cekirdek boyuna gore degisiyor; sabit
        # bir bolen yerine haritanin kendi tepe degerine gore normalize
        # ediyoruz ki strength her base modelde ayni anlama gelsin.
        peak = float(max(np.abs(gx).max(), np.abs(gy).max(), 1e-6))
        dx = (gx / peak) * settings.displace_strength
        dy = (gy / peak) * settings.displace_strength

    grid_x, grid_y = np.meshgrid(
        np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32)
    )
    return (grid_x + dx).astype(np.float32), (grid_y + dy).astype(np.float32)


def apply_displacement(
    layer_rgba: np.ndarray, map_x: np.ndarray, map_y: np.ndarray
) -> np.ndarray:
    """Kivrim haritasina gore tasarimi piksel piksel kaydirir."""
    remapped = cv2.remap(
        layer_rgba,
        map_x,
        map_y,
        interpolation=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )
    # warp_design ile ayni gerekce: kubik tasmayi burada da kirpiyoruz.
    return np.clip(remapped, 0.0, 1.0)


# --------------------------------------------------------------------------
# 3. Golgeleme
# --------------------------------------------------------------------------

def apply_shading(
    layer_rgb: np.ndarray, shading_gray: np.ndarray, strength: float
) -> np.ndarray:
    """Isik/golge haritasini tasarima uygular.

    Harita 128 gri = notr olacak sekilde yorumlanir: bunun altindaki
    degerler karartir, ustundekiler aydinlatir. Boylece tisortun kendi
    golgeleri baskinin uzerine de duser -- tasarimin 'yapistirilmis'
    degil, 'basilmis' gorunmesini saglayan asil sey bu.
    """
    # Notr nokta tam olarak 128 gri. "shade * 2" yazmak cazip ama
    # 128/255 = 0.50196 oldugu icin carpan 1.0039 cikar ve notr bir
    # harita tasarimi hafifce aydinlatir. Notr degere bolerek 128'in
    # birebir kimlik islemi olmasini garantiliyoruz.
    neutral = 128.0 / 255.0
    shade = shading_gray.astype(np.float32) / 255.0
    factor = np.clip(shade / neutral, 0.0, 2.0)[..., None]

    shaded = np.clip(layer_rgb * factor, 0.0, 1.0)
    k = float(np.clip(strength, 0.0, 1.0))
    return layer_rgb * (1.0 - k) + shaded * k


# --------------------------------------------------------------------------
# 4-5. Maske ve kompozit
# --------------------------------------------------------------------------

def composite(
    base_rgb: np.ndarray,
    design_rgb: np.ndarray,
    alpha: np.ndarray,
) -> np.ndarray:
    """Tasarimi base gorselin uzerine alfa harmanlamasiyla bindirir."""
    a = alpha[..., None]
    return base_rgb * (1.0 - a) + design_rgb * a


def render(
    base_rgb: np.ndarray,
    design_rgba: np.ndarray,
    print_mask: np.ndarray,
    displace_gray: np.ndarray,
    shading_gray: np.ndarray,
    quad: np.ndarray,
    settings: CompositeSettings,
) -> np.ndarray:
    """Tum hatti sirayla calistirir. float32 [0,1] girer, float32 [0,1] cikar.

    base_rgb    : H x W x 3
    design_rgba : h x w x 4
    """
    h, w = base_rgb.shape[:2]

    # 1. Perspektif
    warped = warp_design(design_rgba, quad, (w, h), settings.design_scale)

    # 2. Displacement -- renk ve alfa AYNI haritayla kaydirilmali,
    #    aksi halde tasarimin kenarinda renk/alfa kaymasi olusur.
    map_x, map_y = build_displacement_maps(displace_gray, settings)
    displaced = apply_displacement(warped, map_x, map_y)

    design_rgb = displaced[..., :3]
    design_alpha = displaced[..., 3]

    # 3. Golgeleme
    shaded = apply_shading(design_rgb, shading_gray, settings.shading_strength)

    # 4. Maskeleme
    mask = print_mask.astype(np.float32) / 255.0
    if settings.edge_feather > 0:
        k = settings.edge_feather * 2 + 1
        mask = cv2.GaussianBlur(mask, (k, k), 0)

    alpha = np.clip(design_alpha * mask, 0.0, 1.0)

    # 5. Kompozit
    return composite(base_rgb, shaded, alpha)
