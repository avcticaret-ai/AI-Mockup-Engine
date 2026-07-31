#!/usr/bin/env python3
"""Dosya yapısını doğrular. Herhangi bir şeyi çalıştırmadan önce bunu çalıştır.

    python check_layout.py

Motorun tamamı `Path(__file__).parent` ile göreli yol kuruyor. Yani bu
dosyanın bulunduğu klasör motorun köküdür ve altındaki düzen ŞART.
Klasörler taşınırsa hiçbir araç çalışmaz -- ama hatalar anlaşılmaz
`ImportError` veya "model bulunamadı" olarak çıkar. Bu script gerçek
sebebi söylüyor.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

REQUIRED_FILES = [
    "batch.py",
    "cli.py",
    "server.py",
    "requirements.txt",
    "SOP-GercekBC3001.md",
    "mockup_engine/__init__.py",
    "mockup_engine/compositor.py",
    "mockup_engine/library.py",
    "mockup_engine/pipeline.py",
    "mockup_engine/recolor.py",
    "comfybridge/__init__.py",
    "comfybridge/client.py",
    "comfybridge/variants.json",
    "comfybridge/workflows/zimage_blank_tee.json",
    "tools/auto_mask.py",
    "tools/calibrate_quad.py",
    "tools/generate_bases.py",
    "tools/export_etsy.py",
    "tools/prepare_base.py",
    "tools/verify_recolor.py",
    "tools/verify_preservation.py",
]

REQUIRED_DIRS = [
    "assets/base-library",
    "tasarimlar",
]

# Yanlis yapida sik gorulen izler. Varsa kullanici klasorleri
# tasimis/duzlestirmis demektir.
WRONG_SIGNS = {
    "comfy": "ComfyUI'in kendi 'comfy' paketiyle cakisir. 'comfybridge' olmali.",
    "variants": "variants bir KLASOR degil, comfybridge/variants.json DOSYASI.",
    "workflows": "workflows engine kokunde degil, comfybridge/workflows altinda olmali.",
    "library": "Bu klasor yok. Model kutuphanesi assets/base-library altinda.",
    "templates": "Bu klasor yok. Eski mimari plandan kalmis olabilir.",
    "engine": "Ic ice 'engine' klasoru. Bu dosyanin bulundugu yer zaten kok.",
}

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
if sys.platform == "win32":
    import os
    os.system("")  # Windows terminalinde ANSI renklerini etkinlestir


def ok(msg: str) -> None:
    print(f"  {GREEN}[tamam]{RESET} {msg}")


def bad(msg: str) -> None:
    print(f"  {RED}[HATA] {RESET} {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}[uyari]{RESET} {msg}")


def main() -> int:
    print(f"\nMotor koku: {ROOT}\n")
    errors = 0

    # -- 1. zorunlu dosyalar ------------------------------------------------
    print("1. Zorunlu dosyalar")
    for rel in REQUIRED_FILES:
        if (ROOT / rel).is_file():
            ok(rel)
        else:
            bad(f"{rel}  EKSIK")
            errors += 1

    # -- 2. zorunlu klasorler ----------------------------------------------
    print("\n2. Zorunlu klasorler")
    for rel in REQUIRED_DIRS:
        if (ROOT / rel).is_dir():
            ok(rel + "/")
        else:
            bad(f"{rel}/  EKSIK")
            errors += 1

    # -- 3. yanlis yapi izleri ---------------------------------------------
    print("\n3. Yanlis yerlestirme izleri")
    found_wrong = False
    for name, why in WRONG_SIGNS.items():
        target = ROOT / name
        if target.exists():
            bad(f"{name}{'/' if target.is_dir() else ''}  -> {why}")
            found_wrong = True
            errors += 1
    if not found_wrong:
        ok("temiz")

    # -- 4. importlar -------------------------------------------------------
    print("\n4. Import kontrolu")
    sys.path.insert(0, str(ROOT))
    for module in ("mockup_engine", "comfybridge.client"):
        try:
            __import__(module)
            ok(f"import {module}")
        except Exception as err:
            bad(f"import {module}  ->  {type(err).__name__}: {err}")
            errors += 1

    # -- 5. is akisi butunlugu ---------------------------------------------
    print("\n5. ComfyUI is akisi")
    try:
        from comfybridge.client import load_workflow, validate_links
        wf = load_workflow(ROOT / "comfybridge" / "workflows" / "zimage_blank_tee.json")
        problems = validate_links(wf)
        if problems:
            for p in problems:
                bad(p)
            errors += len(problems)
        else:
            ok(f"{len(wf)} node, baglantilar tutarli")
    except Exception as err:
        bad(f"okunamadi: {err}")
        errors += 1

    # -- 6. base model kutuphanesi -----------------------------------------
    print("\n6. Base model kutuphanesi")
    try:
        from mockup_engine import list_models, load_model
        lib = ROOT / "assets" / "base-library"
        models = list_models(lib)

        if not models:
            warn("kutuphane bos -- once tools/generate_bases.py calistir")
        for mid in models:
            missing = [
                f for f in ("base.png", "garment_mask.png", "print_mask.png",
                            "displace.png", "shading.png")
                if not (lib / mid / f).exists()
            ]
            if missing:
                warn(f"{mid}  eksik: {', '.join(missing)}")
            else:
                try:
                    m = load_model(mid, lib)
                    quad = "quad var" if m.meta.get("print_quad") else "quad YOK"
                    w, h = m.size
                    ok(f"{mid}  {w}x{h}  {quad}")
                except Exception as err:
                    bad(f"{mid}  yuklenemedi: {err}")
                    errors += 1
    except Exception as err:
        bad(f"kutuphane okunamadi: {err}")
        errors += 1

    # -- 7. bagimliliklar ---------------------------------------------------
    print("\n7. Bagimliliklar")
    for pkg, label in (("cv2", "opencv"), ("numpy", "numpy"), ("PIL", "pillow")):
        try:
            mod = __import__(pkg)
            ver = getattr(mod, "__version__", "?")
            ok(f"{label} {ver}")
        except ImportError:
            bad(f"{label} kurulu degil  ->  pip install -r requirements.txt")
            errors += 1

    # -- sonuc --------------------------------------------------------------
    print()
    if errors:
        print(f"{RED}{errors} sorun bulundu.{RESET} Yukaridakileri duzeltmeden devam etme.\n")
        return 1

    print(f"{GREEN}Yapi dogru.{RESET}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
