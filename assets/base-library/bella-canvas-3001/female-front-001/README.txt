Bu klasor Faz 0.5 icin hazir bekliyor.

SIRALAMA
  1. Nim ile uretilen base gorseli buraya  base.png  olarak kaydet
  2. GIMP/Photoshop ile tisort alanini maskele ->  garment_mask.png
     (255 = tisort, 0 = disari; base.png ile AYNI piksel boyutunda)
  3. python tools/calibrate_quad.py bella-canvas-3001/female-front-001
  4. python tools/prepare_base.py  bella-canvas-3001/female-front-001
  5. python cli.py tasarim.png --model bella-canvas-3001/female-front-001

Adim 4 su uc dosyayi otomatik uretir:
  print_mask.png   displace.png   shading.png
