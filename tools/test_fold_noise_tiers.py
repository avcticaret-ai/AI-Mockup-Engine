#!/usr/bin/env python3
"""verify_asset.py kivrim/gurultu esiklerinin regresyon testi.

    python tools/test_fold_noise_tiers.py

Gercek bir assetin displacement haritasina kontrollu gurultu ekleyerek
uc bandin da dogru tetiklendigini ve cikis kodunun yalnizca ERROR
durumunda 1 oldugunu dogrular.

    >= 1.50           PASS   cikis 0
    1.20 <= r < 1.50  WARN   cikis 0  (asset publishable kalir)
    <  1.20           ERROR  cikis 1

Gecici bir asset klasoru olusturur ve sonunda siler.
"""
import cv2, numpy as np, shutil, subprocess, sys
from pathlib import Path

SRC = Path('assets/base-library/bella-canvas-3001/flat-ref-001')
TMP = Path('assets/base-library/_tier_test')

def build(noise_amp, seed=1):
    """Gercek displace haritasina gurultu ekleyerek orani dusurur."""
    if TMP.exists(): shutil.rmtree(TMP)
    shutil.copytree(SRC, TMP)
    d = cv2.imread(str(TMP/'displace.png'), 0).astype(np.float32)
    g = cv2.imread(str(TMP/'garment_mask.png'), 0) > 127
    rng = np.random.default_rng(seed)
    n = rng.normal(0, noise_amp, d.shape).astype(np.float32)
    out = np.where(g, np.clip(d + n, 0, 255), 128)
    cv2.imwrite(str(TMP/'displace.png'), out.astype(np.uint8))
    # olculen orani dondur
    d32 = out.astype(np.float32)
    s = cv2.GaussianBlur(d32,(0,0),8)
    return (s[g]-s[g].mean()).std() / max((d32-s)[g].std(),1e-6)

print(f"{'gurultu':>9}{'oran':>8}{'cikis':>7}  beklenen / gorulen")
print('-'*62)
results=[]
for amp, expect in [(0.0,'PASS'), (6.0,'PASS'), (11.0,'WARN'), (30.0,'ERROR')]:
    ratio = build(amp)
    p = subprocess.run([sys.executable,'tools/verify_asset.py','_tier_test'],
                       capture_output=True, text=True)
    out = p.stdout
    if 'kivrim sinyali zayif' in out: got='WARN'
    elif 'Kivrim sinyali yetersiz' in out: got='ERROR'
    elif 'kivrim/gurultu' in out: got='PASS'
    else: got='?'
    mark = 'OK' if got==expect else 'UYUSMADI'
    print(f"{amp:>9.1f}{ratio:>8.2f}{p.returncode:>7}  {expect:<6} / {got:<6} {mark}")
    results.append((expect,got,p.returncode))

print()
ok=True
for expect,got,rc in results:
    if expect!=got: ok=False
    # exit code yalnizca ERROR'da 1 olmali
    if expect in ('PASS','WARN') and rc!=0: print(f'  HATA: {expect} durumunda cikis {rc}, 0 olmali'); ok=False
    if expect=='ERROR' and rc==0: print('  HATA: ERROR durumunda cikis 0, 1 olmali'); ok=False
shutil.rmtree(TMP, ignore_errors=True)
print('TUM BANTLAR DOGRU' if ok else 'BASARISIZ')
sys.exit(0 if ok else 1)
