#!/usr/bin/env python3
"""photo.jpg  ->  tam asset seti  (tek komut)

    python tools/build_asset.py foto.jpg --model bella-canvas-3001/female-front-001
    python tools/build_asset.py foto.jpg --model <id> --size L --method cloth

NEDEN GEREKLİ
    Asset üretimi altı ayrı komut ve aralarında elle veri taşınıyordu:
    fotoğrafı kopyala, formatı çevir, maskele, gövde genişliğini ölç,
    inç'e çevir, quad'ı yaz, haritaları türet, doğrula. Asset başına
    ~45 dakika ve her adımda elle hata riski.

    Bu araç kendi mantığını içermez; mevcut araçları sırayla çağırır.
    Tek eklediği şey fotoğraf alımı (format + ön kontrol) ve akışın
    hangi noktada insan gözü beklediğini net söylemek.

AKIŞ
    1. ingest      photo.jpg -> base.png    + cozunurluk/isik on kontrolu
    2. auto_mask   base.png  -> garment_mask.png
    3. derive_quad garment_mask -> meta.json:print_quad  + onizleme
    4. prepare_base -> print_mask.png, displace.png, shading.png
    5. verify_asset -> kabul testi

    3. ve 5. adım GÖZLE KONTROL gerektirir; araç ne bakılacağını söyler.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

ENGINE = Path(__file__).resolve().parent.parent
TOOLS = ENGINE / "tools"
LIBRARY = ENGINE / "assets" / "base-library"

MIN_SHORT_SIDE = 2400          # Etsy 2000 + kirpma payi
MIN_FRAME_L_STD = 8.0          # duz isik esigi (on kontrol)


def run(cmd: list[str], label: str) -> tuple[int, str]:
    print(f"\n--- {label} " + "-" * max(0, 52 - len(label)))
    res = subprocess.run(cmd, capture_output=True, text=True)
    out = (res.stdout or "").rstrip()
    if out:
        print(out)
    if res.returncode != 0 and res.stderr:
        print(res.stderr.rstrip(), file=sys.stderr)
    return res.returncode, out


def ingest(photo: Path, model_dir: Path) -> bool:
    """Fotografi base.png olarak yazar ve on kontrol yapar.

    Uzanti degistirmek yetmez: cv2 ile okuyup PNG olarak yeniden
    kodluyoruz, boylece JPEG sikistirmasi tasinmaz ve dosyanin
    gercekten cozulebilir oldugu dogrulanmis olur.
    """
    print(f"\n--- 1. ingest " + "-" * 44)
    img = cv2.imread(str(photo), cv2.IMREAD_COLOR)
    if img is None:
        print(f"HATA: goruntu okunamadi: {photo}", file=sys.stderr)
        return False

    h, w = img.shape[:2]
    model_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(model_dir / "base.png"), img)
    print(f"  base.png yazildi   : {w}x{h}")

    ok = True
    if min(w, h) < MIN_SHORT_SIDE:
        print(f"  UYARI: kisa kenar {min(w,h)} < {MIN_SHORT_SIDE}. "
              f"Etsy ciktisinda buyutme gerekecek.")

    lab = cv2.cvtColor(img.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)
    l_std = float(lab[..., 0].std())
    print(f"  kare L* std        : {l_std:.2f}", end="")
    if l_std < MIN_FRAME_L_STD:
        print(f"   UYARI: < {MIN_FRAME_L_STD}, isik duz olabilir")
    else:
        print()

    return ok


def seed_meta(model_dir: Path, args) -> None:
    """meta.json'i olustur veya koken alanlarini tamamla.

    Var olan alanlari EZMEZ -- yeniden calistirildiginda elle girilen
    bilgiler korunur.
    """
    path = model_dir / "meta.json"
    meta = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    defaults = {
        "id": args.model,
        "label": args.model.split("/")[-1],
        "brand": args.brand,
        "model": args.garment_model,
        "color": args.color,
        "gender": "",
        "pose": "",
        "environment": "",
        "source": args.source,
        "source_detail": "DOLDURULACAK",
        "verified_garment": False,
        "publishable": False,
        "created": date.today().isoformat(),
        "design_scale": 0.95,
        "displacement": {"strength": 16.0, "blur": 9, "mode": "gradient"},
        "shading": {"strength": 0.85},
        "edge_feather": 0,
    }
    for k, v in defaults.items():
        meta.setdefault(k, v)

    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("photo", help="kaynak fotograf (jpg/png)")
    p.add_argument("--model", required=True, help="hedef model id")
    p.add_argument("--library", default=str(LIBRARY))
    p.add_argument("--size", default="M", help="giysi bedeni (derive_quad)")
    p.add_argument("--asset-type", choices=["auto", "human", "flatlay"],
                   default="auto",
                   help="urun fotografi tipi. auto: maskeleme sonucundan cikarilir")
    p.add_argument("--method", choices=["auto", "classic", "cloth", "flatlay"],
                   default="auto",
                   help="maskeleme yontemi; auto once classic dener")
    p.add_argument("--brand", default="Bella Canvas")
    p.add_argument("--garment-model", default="3001")
    p.add_argument("--color", default="white")
    p.add_argument("--source", default="photographed",
                   choices=["photographed", "licensed", "internet-reference",
                            "ai-generated"])
    p.add_argument("--force", action="store_true", help="mevcut dosyalarin uzerine yaz")
    args = p.parse_args()

    photo = Path(args.photo)
    if not photo.exists():
        print(f"HATA: fotograf bulunamadi: {photo}", file=sys.stderr)
        return 2

    model_dir = Path(args.library) / args.model

    print("=" * 64)
    print("ASSET PIPELINE")
    print(f"  kaynak : {photo}")
    print(f"  hedef  : {model_dir}")
    print("=" * 64)

    if not ingest(photo, model_dir):
        return 2
    seed_meta(model_dir, args)

    # -- 2. maske -----------------------------------------------------------
    force = ["--force"] if args.force else []
    # Sira: classic -> cloth -> flatlay. Human fotograflarinda ilk ikisi
    # zaten basarili oldugu icin flatlay'e hic inilmiyor; mevcut davranis
    # degismiyor.
    if args.method != "auto":
        methods = [args.method]
    elif args.asset_type == "human":
        # ADR: human ve flatlay bagimsiz pipeline'lar. Tip acikca
        # verildiyse diger tipin yontemini hic denemiyoruz.
        methods = ["classic", "cloth"]
    elif args.asset_type == "flatlay":
        methods = ["flatlay"]
    else:
        methods = ["classic", "cloth", "flatlay"]
    masked = False
    used_method = None
    for method in methods:
        rc, out = run([sys.executable, str(TOOLS / "auto_mask.py"), args.model,
                       "--library", args.library, "--method", method,
                       "--debug", "--force"],
                      f"2. auto_mask ({method})")
        if rc == 0 and "UYARI" not in out:
            masked = True
            used_method = method
            break
        if method != methods[-1]:
            print(f"\n  {method} yetersiz, {methods[methods.index(method)+1]} deneniyor")
    if not masked:
        print("\nHATA: maskeleme basarisiz. _debug_mask.png'ye bak, "
              "esikleri elle ayarla:\n"
              f"  python tools/auto_mask.py {args.model} --method cloth --force",
              file=sys.stderr)
        return 1

    # -- 3. quad ------------------------------------------------------------
    # asset_type'i kullanilan maskeleme yonteminden coz. ADR gerekliligi:
    # meta.json asset_type alanini tasimali. "auto" verildiginde tip
    # sonuctan cikariliyor -- flatlay yontemi flatlay fotografi demek.
    asset_type = (args.asset_type if args.asset_type != "auto"
                  else ("flatlay" if used_method == "flatlay" else "human"))
    meta_path = model_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["asset_type"] = asset_type
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    print(f"\n  asset_type: {asset_type}"
          f"{'  (maskeleme yonteminden cikarildi)' if args.asset_type == 'auto' else ''}")

    # Flatlay maskesi flatlay quad hesabi gerektiriyor: ustten cekimde
    # BC3001 spec olculeri gecersiz (kollar yana yayilmis, hangi pikselin
    # 20 inclik "width" oldugu belirsiz).
    quad_args = ["--flatlay"] if asset_type == "flatlay" else []
    rc, _ = run([sys.executable, str(TOOLS / "derive_quad.py"), args.model,
                 "--library", args.library, "--size", args.size] + quad_args,
                f"3. derive_quad{' (flatlay)' if quad_args else ''}")
    quad_warned = rc != 0

    # -- 4. haritalar -------------------------------------------------------
    rc, _ = run([sys.executable, str(TOOLS / "prepare_base.py"), args.model,
                 "--library", args.library, "--force"],
                "4. prepare_base")
    if rc != 0:
        return 1

    # -- 5. dogrulama -------------------------------------------------------
    rc, _ = run([sys.executable, str(TOOLS / "verify_asset.py"), args.model,
                 "--library", args.library, "--render"],
                "5. verify_asset")

    print("\n" + "=" * 64)
    if rc != 0:
        print("ASSET GECERSIZ -- yukaridaki hatalari duzelt")
        print("=" * 64 + "\n")
        return 1

    print("ASSET URETILDI")
    print("=" * 64)
    print(f"""
SENDEN BEKLENENLER (araclar bunlari yapamaz)

  1. GOZLE KONTROL  {model_dir / '_debug_mask.png'}
     Yaka, koltuk alti ve etek cizgisi dogru mu?
     Ten veya fon maskeye sizmis mi?

  2. GOZLE KONTROL  {model_dir / '_quad_preview.png'}
     Yesil dikdortgen gercek baski alanini gosteriyor mu?
     Degilse:  python tools/derive_quad.py {args.model} --top-y <piksel>
{'     UYARI: derive_quad uyari verdi, onizlemeye mutlaka bak.' if quad_warned else ''}

  3. META  {model_dir / 'meta.json'}
     source_detail, gender, pose alanlarini doldur.
     Giysi gercekten {args.brand} {args.garment_model} ise:
       verified_garment = true
     Fotograf senin ve kabul kriterleri gectiyse:
       publishable = true

  4. KALIBRASYON
     python cli.py tasarimlar/test-design.png --model {args.model} --displace 20
     Begendigin degerleri meta.json'a yaz.
     NOT: design_scale'e dokunma, gercek baski alanindan turetildi.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
