#!/usr/bin/env python3
"""Tasarimin piksel olarak korundugunu kanitlar.

Displacement ve shading kapatildiginda, baski alanina dusen pikseller
kaynak tasarimin ayni pikselleri olmali. Yalnizca perspektif olcekleme
kaynakli yeniden ornekleme farki kabul edilebilir.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2, numpy as np
from mockup_engine import load_model, load_design
from mockup_engine.compositor import CompositeSettings, warp_design

ENGINE = Path(__file__).resolve().parent.parent
model = load_model("test-model", ENGINE / "assets" / "base-library")
design = load_design(ENGINE / "tasarimlar" / "test-design.png")

s = CompositeSettings(design_scale=1.0, displace_strength=0.0,
                      shading_strength=0.0, displace_blur=0)
w, h = model.size
warped = warp_design(design, model.print_quad, (w, h), s.design_scale)

# Baski alanindaki opak pikselleri kaynakla karsilastir
alpha = warped[..., 3]
opaque = alpha > 0.99
print(f"opak piksel sayisi        : {opaque.sum():,}")

# Renk kumesi karsilastirmasi: warp yeni RENK uretmemeli
src_colors = {tuple(np.round(c, 2)) for c in
              design[design[..., 3] > 0.99][:, :3].reshape(-1, 3)[::97]}
dst_colors = {tuple(np.round(c, 2)) for c in
              warped[opaque][:, :3].reshape(-1, 3)[::97]}
novel = dst_colors - src_colors
print(f"kaynak renk cesidi        : {len(src_colors)}")
print(f"cikti renk cesidi         : {len(dst_colors)}")
print(f"kaynakta olmayan renk     : {len(novel)}  (interpolasyon kaynakli)")

# Shading kapaliyken renkler aynen gecmeli
from mockup_engine.compositor import apply_shading
neutral = np.full((h, w), 128, np.uint8)
out = apply_shading(warped[..., :3], neutral, 1.0)
delta = np.abs(out - warped[..., :3]).max()
print(f"notr golgede maks sapma   : {delta:.6f}  (0 olmali)")

# Displacement kapaliyken kaydirma olmamali
from mockup_engine.compositor import build_displacement_maps, apply_displacement
mx, my = build_displacement_maps(model.displace, s)
still = apply_displacement(warped, mx, my)
print(f"sifir displacement sapma  : {np.abs(still - warped).max():.6f}  (~0 olmali)")
