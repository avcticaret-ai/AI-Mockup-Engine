#!/usr/bin/env python3
"""Piksel korunumunu kanitlamak icin test tasarimi uretir.

Ince yazi, sac teli cizgiler ve keskin kenarlar iceriyor -- bunlar
bir diffusion modelinin ilk bozacagi seyler. CV hattinda bozulmamali.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W = H = 1600
OUT = Path(__file__).resolve().parent.parent / "tasarimlar" / "test-design.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

INK = (17, 24, 39, 255)
ACCENT = (220, 38, 38, 255)

def font(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

# dis cember
d.ellipse([60, 60, W-60, H-60], outline=INK, width=14)
# sac teli cizgiler -- displacement'i gorsel olarak ele verir
for i in range(24):
    y = 250 + i * 6
    d.line([(300, y), (W-300, y)], fill=INK, width=1)

d.text((W//2, 620), "AVCI", font=font(240), fill=INK, anchor="mm")
d.text((W//2, 800), "TICARET", font=font(96), fill=ACCENT, anchor="mm")
d.text((W//2, 900), "EST. 2026 . ANKARA", font=font(46), fill=INK, anchor="mm")

# ince punto -- kalite testinin asil olcusu
d.text((W//2, 1010), "bu satir 18 punto ve okunabilir kalmali",
       font=font(34), fill=INK, anchor="mm")

# keskin geometri
d.rectangle([560, 1120, 1040, 1180], fill=ACCENT)
for i in range(9):
    x = 560 + i * 60
    d.line([(x, 1240), (x, 1400)], fill=INK, width=3)

img.save(OUT)
print(f"{OUT}  {img.size}")
