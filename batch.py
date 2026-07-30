#!/usr/bin/env python3
"""Toplu mockup üretimi: tasarım × model × renk çapraz çarpımı.

    python batch.py tasarim.png --colors white,black,navy
    python batch.py --designs tasarimlar --models all --colors all
    python batch.py --designs tasarimlar --product bella-canvas-3001 \
                    --colors white,black --workers 4

Renkler klasör DEĞİLDİR. `recolor.py` beş rengi tek beyaz base'den
çalışma anında türetiyor; kütüphanede renk başına asset tutulmuyor.
Model id ise kütüphaneye göre GÖRELİ YOL: "bella-canvas-3001/pose-01-front".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from mockup_engine import (  # noqa: E402
    COLOR_PRESETS, LibraryError, generate_mockup, list_models,
)


def default_workers() -> int:
    """Cekirdek sayisini asma. Tek cekirdekli makinede paralellik
    hizlandirmaz, yalnizca baglam degistirme maliyeti ekler."""
    return max(1, min(4, os.cpu_count() or 1))


def tune_opencv(workers: int) -> int:
    """OpenCV zaten kendi icinde cok cekirdekli calisiyor.

    N worker x her biri tum cekirdekler = thread bogusmasi. Olculdu:
    tek cekirdekli makinede 4 worker, 1 worker'a gore 1.7 kat YAVAS.
    Cekirdekleri worker'lara boluyoruz.
    """
    cpu = os.cpu_count() or 1
    per_worker = max(1, cpu // max(workers, 1))
    cv2.setNumThreads(per_worker)
    return per_worker

LIBRARY = ROOT / "assets" / "base-library"
DEFAULT_OUT = ROOT / "outputs" / "batch"


def collect_designs(args) -> list[Path]:
    if args.design:
        p = Path(args.design)
        if not p.is_file():
            raise SystemExit(f"HATA: tasarım bulunamadı: {p}")
        return [p]

    d = Path(args.designs)
    if not d.is_dir():
        raise SystemExit(f"HATA: tasarım klasörü yok: {d}")

    files = sorted(
        f for f in d.iterdir()
        if f.suffix.lower() in (".png", ".webp") and not f.name.startswith("_")
    )
    if not files:
        raise SystemExit(f"HATA: {d} içinde .png tasarım yok")
    return files


def collect_models(args) -> list[str]:
    available = list_models(LIBRARY)
    if not available:
        raise SystemExit(
            f"HATA: kütüphane boş: {LIBRARY}\n"
            "Önce base asset üret: python tools/generate_bases.py"
        )

    if args.product:
        chosen = [m for m in available if m.split("/")[0] == args.product]
        if not chosen:
            raise SystemExit(
                f"HATA: '{args.product}' ürünü altında model yok.\n"
                f"Kütüphanedekiler: {', '.join(available)}"
            )
        return chosen

    if not args.models or args.models == ["all"]:
        return available

    unknown = [m for m in args.models if m not in available]
    if unknown:
        raise SystemExit(
            f"HATA: bilinmeyen model: {', '.join(unknown)}\n"
            f"Kütüphanedekiler: {', '.join(available)}"
        )
    return args.models


def collect_colors(args) -> list[str | None]:
    if not args.colors:
        return [None]                       # renk değiştirme yok
    if args.colors == ["all"]:
        return list(COLOR_PRESETS)

    for c in args.colors:
        low = c.strip().lower()
        if low not in COLOR_PRESETS and not (low.startswith("#") and len(low) == 7):
            raise SystemExit(
                f"HATA: geçersiz renk '{c}'.\n"
                f"Presetler: {', '.join(COLOR_PRESETS)} veya #RRGGBB"
            )
    return [c.strip().lower() for c in args.colors]


def build_jobs(designs, models, colors, out_root: Path, overrides) -> list[dict]:
    jobs = []
    for design in designs:
        for model in models:
            for color in colors:
                safe_model = model.replace("/", "_")
                name = f"{safe_model}{'-' + color.lstrip('#') if color else ''}.png"
                jobs.append({
                    "design": design,
                    "model_id": model,
                    "color": color,
                    "out": out_root / design.stem / name,
                    "overrides": overrides,
                })
    return jobs


def run_job(job: dict) -> dict:
    started = time.perf_counter()
    try:
        generate_mockup(
            design_path=job["design"],
            model_id=job["model_id"],
            library_dir=LIBRARY,
            output_path=job["out"],
            overrides=job["overrides"],
            color=job["color"],
        )
        return {**job, "ok": True, "ms": round((time.perf_counter() - started) * 1000)}
    except (LibraryError, ValueError, OSError) as err:
        return {**job, "ok": False, "error": f"{type(err).__name__}: {err}"}


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)

    p.add_argument("design", nargs="?", help="tek tasarım dosyası")
    p.add_argument("--designs", default="tasarimlar", help="tasarım klasörü")
    p.add_argument("--models", nargs="+", help="model id listesi veya 'all'")
    p.add_argument("--product", help="bir ürünün tüm pozları, ör. bella-canvas-3001")
    p.add_argument("--colors", type=lambda s: s.split(","),
                   help="virgülle ayrılmış renkler veya 'all'")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="çıktı kökü")
    p.add_argument("--workers", type=int, default=None,
                   help=f"eşzamanlı render (varsayılan: {default_workers()}, "
                        f"çekirdek sayısına göre)")
    p.add_argument("--scale", type=float, help="tasarım doluluk oranı")
    p.add_argument("--displace", type=float, help="kıvrım gücü")
    p.add_argument("--shading", type=float, help="gölge şiddeti")
    p.add_argument("--dry-run", action="store_true", help="sadece planı göster")
    args = p.parse_args()

    if args.workers is None:
        args.workers = default_workers()
    args.workers = max(1, args.workers)
    per_worker = tune_opencv(args.workers)

    designs = collect_designs(args)
    models = collect_models(args)
    colors = collect_colors(args)

    overrides = {}
    if args.scale is not None:
        overrides["design_scale"] = args.scale
    if args.displace is not None:
        overrides["displacement"] = {"strength": args.displace}
    if args.shading is not None:
        overrides["shading"] = {"strength": args.shading}

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_root = Path(args.out) / stamp
    jobs = build_jobs(designs, models, colors, out_root, overrides or None)

    print("=" * 64)
    print("AI MOCKUP ENGINE — TOPLU ÜRETİM")
    print("=" * 64)
    print(f"Tasarım  : {len(designs)}  ({', '.join(d.name for d in designs[:4])}"
          f"{' ...' if len(designs) > 4 else ''})")
    print(f"Model    : {len(models)}  ({', '.join(models[:4])}"
          f"{' ...' if len(models) > 4 else ''})")
    print(f"Renk     : {', '.join(c or '(değişiklik yok)' for c in colors)}")
    print(f"Toplam   : {len(jobs)} mockup")
    print(f"Çıktı    : {out_root}")
    print(f"Paralel  : {args.workers} worker x {per_worker} OpenCV thread "
          f"({os.cpu_count()} çekirdek)")
    print("=" * 64)

    if args.dry_run:
        for j in jobs:
            print(f"  {j['design'].name}  ->  {j['model_id']}  "
                  f"{j['color'] or '-'}  ->  {j['out'].relative_to(Path(args.out))}")
        return 0

    for d in {j["out"].parent for j in jobs}:
        d.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    results: list[dict] = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_job, j): j for j in jobs}
        for i, future in enumerate(as_completed(futures), 1):
            r = future.result()
            results.append(r)
            tag = f"{r['model_id']} {r['color'] or ''}".strip()
            if r["ok"]:
                print(f"  [{i:>3}/{len(jobs)}] {r['design'].stem}  {tag}  "
                      f"{r['ms']} ms")
            else:
                print(f"  [{i:>3}/{len(jobs)}] {r['design'].stem}  {tag}  "
                      f"HATA: {r['error']}", file=sys.stderr)

    elapsed = time.perf_counter() - started
    ok = [r for r in results if r["ok"]]

    manifest = {
        "created": stamp,
        "designs": [str(d) for d in designs],
        "models": models,
        "colors": colors,
        "overrides": overrides or None,
        "requested": len(jobs),
        "succeeded": len(ok),
        "failed": len(jobs) - len(ok),
        "elapsed_seconds": round(elapsed, 2),
        "results": [
            {
                "design": r["design"].name,
                "model_id": r["model_id"],
                "color": r["color"],
                "file": str(r["out"].relative_to(out_root)) if r["ok"] else None,
                "ok": r["ok"],
                "error": r.get("error"),
            }
            for r in sorted(results, key=lambda x: (x["design"].name, x["model_id"],
                                                    x["color"] or ""))
        ],
    }
    (out_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=" * 64)
    print(f"Başarılı : {len(ok)}/{len(jobs)}")
    if len(ok) < len(jobs):
        print(f"Hatalı   : {len(jobs) - len(ok)}")
    print(f"Süre     : {elapsed:.1f} sn  ({elapsed / max(len(jobs), 1):.2f} sn/mockup)")
    print(f"Çıktı    : {out_root}")
    print("=" * 64)

    return 0 if len(ok) == len(jobs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
