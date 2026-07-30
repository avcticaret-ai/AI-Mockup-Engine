#!/usr/bin/env python3
"""ComfyUI ile boş tişört base görsellerini toplu üretir ve kütüphaneye yazar.

    python tools/generate_bases.py --check            # sadece ortamı doğrula
    python tools/generate_bases.py --list             # varyantları listele
    python tools/generate_bases.py --only female-front-001
    python tools/generate_bases.py                    # hepsini üret

Her varyant için şunlar oluşur:

    assets/base-library/bella-canvas-3001/<varyant-id>/
        base.png       ← ComfyUI çıktısı
        meta.json      ← köken alanları doldurulmuş iskelet

Sonraki adımlar (ayrı araçlar):
    tools/auto_mask.py      -> garment_mask.png
    tools/calibrate_quad.py -> print_quad
    tools/prepare_base.py   -> print_mask / displace / shading
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from comfybridge.client import (  # noqa: E402
    ComfyClient, ComfyError, apply, load_workflow, validate_links,
)

ENGINE = Path(__file__).resolve().parent.parent
WORKFLOW = ENGINE / "comfybridge" / "workflows" / "zimage_blank_tee.json"
VARIANTS = ENGINE / "comfybridge" / "variants.json"
LIBRARY = ENGINE / "assets" / "base-library"

# Is akisindaki node id'leri. Sablonu degistirirsen burayi da guncelle.
NODE_POSITIVE = "4"
NODE_LATENT = "6"
NODE_SAMPLER = "7"
NODE_SHIFT = "2"


def build_prompt(spec: dict, variant: dict) -> str:
    fields = {**spec["defaults"], **variant}
    return spec["prompt_template"].format(
        subject=fields["subject"],
        framing=fields["framing"],
        pose=fields["pose"],
        environment=fields["environment"],
    )


def variant_dir(spec: dict, variant: dict) -> Path:
    return LIBRARY / spec["product"] / variant["id"]


def write_meta(spec: dict, variant: dict, path: Path, prompt: str, seed: int) -> None:
    """meta.json iskeleti. Köken alanları burada doldurulur.

    100+ modele çıkarken hangi asset'in AI üretimi olduğunu ayırt etmenin
    tek yolu bu -- ve Etsy'ye hangi görselleri koyabileceğini bu belirliyor.
    """
    meta = {
        "id": f"{spec['product']}/{variant['id']}",
        "label": variant["id"],
        "brand": "Bella Canvas",
        "model": "3001",
        "color": "white",
        "gender": variant.get("gender", ""),
        "pose": variant.get("pose_label", ""),
        "environment": "studio",

        "source": "ai-generated",
        "source_detail": "ComfyUI / Z-Image Turbo bf16",
        "generation": {
            "seed": seed,
            "steps": spec["defaults"]["steps"],
            "cfg": spec["defaults"]["cfg"],
            "shift": spec["defaults"]["shift"],
            "width": spec["defaults"]["width"],
            "height": spec["defaults"]["height"],
            "prompt": prompt,
        },
        "verified_garment": False,
        "publishable": False,
        "created": date.today().isoformat(),

        "print_quad": [],
        "design_scale": 0.9,
        "displacement": {"strength": 16.0, "blur": 9, "mode": "gradient"},
        "shading": {"strength": 0.85},
        "edge_feather": 0,
    }
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8188)
    p.add_argument("--only", action="append", help="sadece bu varyant id'leri")
    p.add_argument("--check", action="store_true", help="sadece ortamı doğrula")
    p.add_argument("--list", action="store_true", help="varyantları listele")
    p.add_argument("--force", action="store_true", help="mevcut base.png üzerine yaz")
    p.add_argument("--timeout", type=float, default=600.0)
    args = p.parse_args()

    spec = json.loads(VARIANTS.read_text(encoding="utf-8"))
    workflow = load_workflow(WORKFLOW)

    if args.list:
        print(f"\n{spec['product']} — {len(spec['variants'])} varyant\n")
        for v in spec["variants"]:
            print(f"  {v['id']:<28} {v.get('gender',''):<8} seed={v.get('seed')}")
        print()
        return 0

    # 1. İş akışı bağlantı bütünlüğü (ComfyUI'a hiç gitmeden)
    problems = validate_links(workflow)
    if problems:
        print("İŞ AKIŞI BOZUK:", file=sys.stderr)
        for pr in problems:
            print(f"  {pr}", file=sys.stderr)
        return 1
    print(f"iş akışı bağlantıları  : tamam ({len(workflow)} node)")

    # 2. ComfyUI ayakta mı
    client = ComfyClient(args.host, args.port)
    if not client.ping():
        print(f"\nHATA: ComfyUI {args.host}:{args.port} adresinde yanıt vermiyor.",
              file=sys.stderr)
        return 1
    print(f"ComfyUI                : {args.host}:{args.port} ayakta")

    # 3. Gerekli node tipleri kurulu mu
    try:
        missing = client.missing_node_types(workflow)
    except ComfyError as err:
        print(f"\nHATA: {err}", file=sys.stderr)
        return 1

    if missing:
        print(f"\nHATA: bu ComfyUI kurulumunda olmayan node tipleri: {', '.join(missing)}",
              file=sys.stderr)
        print("ComfyUI'ı güncelle veya iş akışını düzenle.", file=sys.stderr)
        return 1
    print("node tipleri           : hepsi mevcut")

    if args.check:
        print("\nOrtam hazır.\n")
        return 0

    variants = spec["variants"]
    if args.only:
        wanted = set(args.only)
        variants = [v for v in variants if v["id"] in wanted]
        if not variants:
            print(f"\nHATA: eşleşen varyant yok: {', '.join(args.only)}", file=sys.stderr)
            return 1

    print(f"\n{len(variants)} varyant üretilecek\n")

    produced = 0
    for i, variant in enumerate(variants, 1):
        out_dir = variant_dir(spec, variant)
        base_path = out_dir / "base.png"

        if base_path.exists() and not args.force:
            print(f"[{i}/{len(variants)}] {variant['id']}  — zaten var, atlanıyor")
            continue

        prompt = build_prompt(spec, variant)
        seed = int(variant.get("seed", 0))
        d = spec["defaults"]

        wf = apply(workflow, NODE_POSITIVE, text=prompt)
        wf = apply(wf, NODE_LATENT, width=d["width"], height=d["height"], batch_size=1)
        wf = apply(wf, NODE_SAMPLER, seed=seed, steps=d["steps"], cfg=d["cfg"])
        wf = apply(wf, NODE_SHIFT, shift=d["shift"])

        print(f"[{i}/{len(variants)}] {variant['id']}  seed={seed} ... ", end="", flush=True)

        try:
            images = client.run(wf, timeout=args.timeout)
        except ComfyError as err:
            print("HATA")
            print(f"    {err}", file=sys.stderr)
            continue

        if not images:
            print("görsel dönmedi")
            continue

        out_dir.mkdir(parents=True, exist_ok=True)
        base_path.write_bytes(images[0].data)
        write_meta(spec, variant, out_dir / "meta.json", prompt, seed)

        size_mb = len(images[0].data) / 1_048_576
        print(f"tamam ({size_mb:.1f} MB)")
        produced += 1

    print(f"\n{produced} base görsel üretildi -> {LIBRARY / spec['product']}\n")
    if produced:
        print("Sıradaki adımlar:")
        print("  1. Her base.png'yi %100 zoom'da göğüsten kontrol et")
        print("     (AI beyaz tişörtlere hayali logo/cep/etiket ekliyor)")
        print("  2. python tools/auto_mask.py <urun>/<varyant>")
        print("  3. python tools/calibrate_quad.py <urun>/<varyant>")
        print("  4. python tools/prepare_base.py <urun>/<varyant>\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
