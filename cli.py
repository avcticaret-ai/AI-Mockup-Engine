#!/usr/bin/env python3
"""AI Mockup Engine -- komut satiri arayuzu.

    python cli.py design.png --model test-model
    python cli.py design.png --model test-model --scale 0.85 --displace 18
    python cli.py --list

Cikti varsayilan olarak outputs/mockup.png.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mockup_engine import LibraryError, generate_mockup, list_models

ENGINE_DIR = Path(__file__).resolve().parent
LIBRARY_DIR = ENGINE_DIR / "assets" / "base-library"
OUTPUT_DIR = ENGINE_DIR / "outputs"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Bir PNG tasarimi base model uzerine gercekci sekilde giydirir.",
    )
    parser.add_argument("design", nargs="?", help="Tasarim PNG dosyasi")
    parser.add_argument("--model", default="test-model", help="Base model id")
    parser.add_argument("--out", help="Cikti dosyasi (varsayilan outputs/mockup.png)")
    parser.add_argument("--list", action="store_true", help="Base modelleri listele")

    # meta.json'daki degerleri gecici olarak ezmek icin -- kalibrasyon
    # yaparken dosyayi surekli duzenlemek yerine burasi kullanilir.
    tuning = parser.add_argument_group("kalibrasyon (meta.json'u gecici ezer)")
    tuning.add_argument("--scale", type=float, help="Tasarim doluluk orani, or. 0.85")
    tuning.add_argument("--displace", type=float, help="Kivrim gucu (piksel)")
    tuning.add_argument("--shading", type=float, help="Golge siddeti 0-1")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list:
        models = list_models(LIBRARY_DIR)
        if not models:
            print(f"Kutuphane bos: {LIBRARY_DIR}")
        else:
            print(f"\n{len(models)} base model:\n")
            for m in models:
                print(f"  {m}")
            print()
        return 0

    if not args.design:
        build_parser().print_help()
        return 1

    design_path = Path(args.design)
    if not design_path.exists():
        print(f"HATA: tasarim bulunamadi: {design_path}", file=sys.stderr)
        return 1

    output_path = Path(args.out) if args.out else OUTPUT_DIR / "mockup.png"

    overrides = {}
    if args.scale is not None:
        overrides["design_scale"] = args.scale
    if args.displace is not None:
        overrides["displacement"] = {"strength": args.displace}
    if args.shading is not None:
        overrides["shading"] = {"strength": args.shading}

    try:
        result = generate_mockup(
            design_path=design_path,
            model_id=args.model,
            library_dir=LIBRARY_DIR,
            output_path=output_path,
            overrides=overrides or None,
        )
    except (LibraryError, FileNotFoundError) as err:
        print(f"HATA: {err}", file=sys.stderr)
        return 1

    print(f"\nTasarim : {design_path.name}")
    print(f"Model   : {args.model}")
    print(f"Cikti   : {result}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
