"""AI Mockup Engine — HTTP API katmanı.

    uvicorn server:app --host 127.0.0.1 --port 8080 --reload

Bu dosya HİÇBİR görüntü işleme mantığı içermez. Tek işi HTTP isteğini
`mockup_engine.generate_mockup()` çağrısına çevirmek. Compositor,
recolor ve kütüphane mantığı tek yerde kalır -- API ile CLI birebir
aynı çıktıyı üretir.

Uç noktalar
    GET  /health                     durum + kütüphanedeki modeller
    GET  /colors                     renk presetleri
    POST /render                     tek mockup (multipart VEYA json)
    POST /batch-render               model x renk matrisi
    GET  /outputs/{job_id}/{dosya}   toplu çıktıları indir
    GET  /outputs/{job_id}.zip       toplu çıktıları zip olarak indir
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import ipaddress
import json
import logging
import os
import shutil
import socket
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.background import BackgroundTask

from mockup_engine import COLOR_PRESETS, LibraryError, generate_mockup, list_models

# --------------------------------------------------------------------------
# Yapılandırma
# --------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
LIBRARY_DIR = ROOT / "assets" / "base-library"
JOBS_DIR = ROOT / "outputs" / "api"

MAX_UPLOAD_BYTES = int(os.getenv("MOCKUP_MAX_UPLOAD_MB", "40")) * 1024 * 1024
MAX_BATCH_ITEMS = int(os.getenv("MOCKUP_MAX_BATCH", "50"))
# Cekirdek sayisini asma: OpenCV zaten kendi icinde cok cekirdekli,
# oversubscription olcume gore ciddi yavaslama yapiyor.
RENDER_WORKERS = int(os.getenv("MOCKUP_WORKERS", "0")) or max(1, min(4, os.cpu_count() or 1))
JOB_TTL_SECONDS = int(os.getenv("MOCKUP_JOB_TTL", "3600"))
ALLOW_URL_FETCH = os.getenv("MOCKUP_ALLOW_URL_FETCH", "1") == "1"

# Next.js gibi tarayıcı istemcileri için. Üretimde daralt.
CORS_ORIGINS = [o.strip() for o in os.getenv("MOCKUP_CORS", "*").split(",")]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
)
log = logging.getLogger("mockup.api")

# CPU-bağımlı iş için thread havuzu.
# ProcessPool değil ThreadPool: OpenCV ve NumPy ağır işlemlerde GIL'i
# bırakıyor, yani thread'ler gerçek paralellik veriyor. ProcessPool
# Windows'ta spawn + pickle maliyeti getirir ve --reload ile sorun çıkarır.
_executor: ThreadPoolExecutor | None = None
_slots: asyncio.Semaphore | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _executor, _slots
    _executor = ThreadPoolExecutor(max_workers=RENDER_WORKERS,
                                   thread_name_prefix="render")
    _slots = asyncio.Semaphore(RENDER_WORKERS)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)

    # OpenCV ic thread'lerini worker'lara bol.
    cv2.setNumThreads(max(1, (os.cpu_count() or 1) // RENDER_WORKERS))
    log.info("paralellik: %d worker x %d OpenCV thread (%d cekirdek)",
             RENDER_WORKERS, cv2.getNumThreads(), os.cpu_count() or 1)

    models = list_models(LIBRARY_DIR)
    log.info("kütüphane: %d model  (%s)", len(models), LIBRARY_DIR)
    if not models:
        log.warning("kütüphane BOŞ -- önce base asset üret")

    _purge_expired_jobs()
    yield

    _executor.shutdown(wait=True)


# Arayuzun bekledigi yetenekler. Yeni bir /render parametresi
# eklendiginde buraya da yazilmali; arayuz eksigi fark edip
# kullaniciyi uyariyor.
API_VERSION = "1.5.0"
BUILD = "2026.08.03-3"
CAPABILITIES = {
    "render", "batch", "preview", "meta", "quad_save",
    "flip",        # flip_h / flip_v  -- server.py'de, tasarim ceviriliyor
    "scale3",      # design_scale ust siniri 3.0
}


def _pipeline_build() -> str:
    """pipeline.py'nin BUILD damgasi. Uyumsuzluk tespiti icin."""
    try:
        from mockup_engine import pipeline as _pl
        return str(getattr(_pl, "BUILD", "bilinmiyor"))
    except Exception:
        return "okunamadi"


def _pipeline_supports_quad_override() -> bool:
    """mockup_engine/pipeline.py quad override destekliyor mu?

    offset_x/offset_y/rotate parametreleri server.py'de quad'a
    donusturuluyor ama UYGULAMA pipeline.py'de. Eski bir pipeline.py
    ile server.py yeni olursa:

        X-Applied: quad_override=true     (server ekliyor)
        render:    DEGISMIYOR             (pipeline yok sayiyor)

    Bu sessiz uyumsuzluk "tasarimi oynatiyorum ama mockup tepki
    vermiyor" seklinde gorunuyordu. Artik tespit ediliyor.
    """
    try:
        from mockup_engine import pipeline as _pl
        # Bayrak yoksa pipeline eski demektir. Kaynak metnine bakmak
        # yaniltiyordu: yardimci fonksiyon dosyada kalmis ama cagrilmiyor
        # olabiliyor.
        return bool(getattr(_pl, "QUAD_OVERRIDE_SUPPORTED", False))
    except Exception:
        return False


if _pipeline_supports_quad_override():
    CAPABILITIES.add("placement")   # offset_x / offset_y / rotate

app = FastAPI(
    title="AI Mockup Engine API",
    version="1.1.0",
    description="Tasarım PNG'sini base model üzerine gerçekçi biçimde basar.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,   # allow_origins="*" ile True olamaz
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["X-Render-Ms", "X-Applied"],
)


# --------------------------------------------------------------------------
# Şemalar
# --------------------------------------------------------------------------

class RenderParams(BaseModel):
    """POST /render gövdesi (JSON kullanıldığında).

    extra="forbid": bilinmeyen alan gelirse HATA ver. Varsayilan
    davranis onu SESSIZCE YOK SAYMAK ve bu, arayuz yeni bir parametre
    gonderirken sunucu eskiyse "degisiklik yansimiyor" seklinde
    gorunuyordu -- hicbir hata mesaji olmadan.
    """

    model_config = {"extra": "forbid"}

    design_url: str | None = None
    design_base64: str | None = None
    model_id: str = "test-model"
    color: str | None = None
    scale: float | None = Field(None, gt=0, le=3.0)
    displace: float | None = Field(None, ge=0, le=200)
    shading: float | None = Field(None, ge=0, le=1)

    # Konumlandirma. Arayuzde tasarim suruklenip dondurulurken
    # kullaniliyor; meta.json'a yazilmaz, yalnizca bu istek icin gecerli.
    #   offset_x/y : baski alani genisliginin orani cinsinden kaydirma
    #   rotate     : derece, baski alani merkezi etrafinda
    # Sinir +-2.0 idi ve YETMIYORDU. Olculdu: 1200x1600 base uzerinde
    # baski alani 336 px, yani tuvalin bir ucundan digerine gitmek
    # yatayda 3.57, dikeyde 4.76 birim. Kullanici tasarimi kenara
    # tasidiginda HTTP 400 aliyordu.
    offset_x: float | None = Field(None, ge=-6.0, le=6.0)
    offset_y: float | None = Field(None, ge=-6.0, le=6.0)
    rotate: float | None = Field(None, ge=-180.0, le=180.0)

    # Tasarimi aynalama. Motor degismiyor -- tasarim diske yazilmadan
    # once ceviriliyor.
    flip_h: bool = False
    flip_v: bool = False

    response_mode: Literal["file", "json"] = "file"

    @field_validator("color")
    @classmethod
    def _check_color(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if v in COLOR_PRESETS or (v.startswith("#") and len(v) == 7):
            return v
        raise ValueError(
            f"geçersiz renk '{v}'. presetler: {', '.join(COLOR_PRESETS)} veya #RRGGBB"
        )


class BatchItem(BaseModel):
    model_id: str
    color: str | None = None


class BatchParams(BaseModel):
    design_url: str | None = None
    design_base64: str | None = None

    # İki kullanım: ya açık liste, ya çapraz çarpım.
    items: list[BatchItem] | None = None
    model_ids: list[str] | None = None
    colors: list[str] | None = None

    scale: float | None = Field(None, gt=0, le=3.0)
    displace: float | None = Field(None, ge=0, le=200)
    shading: float | None = Field(None, ge=0, le=1)

    def resolve_items(self) -> list[BatchItem]:
        if self.items:
            return self.items
        models = self.model_ids or ["test-model"]
        colors: list[str | None] = list(self.colors) if self.colors else [None]
        return [BatchItem(model_id=m, color=c) for m in models for c in colors]


# --------------------------------------------------------------------------
# Yardımcılar
# --------------------------------------------------------------------------

def _known_models() -> list[str]:
    return list_models(LIBRARY_DIR)


def _assert_model_exists(model_id: str) -> None:
    if model_id not in _known_models():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "model_bulunamadi",
                "model_id": model_id,
                "mevcut": _known_models(),
            },
        )


def _assert_safe_url(url: str) -> None:
    """SSRF koruması.

    design_url açık bir kapıdır: kötü niyetli bir istek sunucunun İÇ
    ağına yönlendirilebilir -- bulut metadata servisi (169.254.169.254),
    yereldeki ComfyUI (127.0.0.1:8188), ya da LAN'daki başka servisler.
    Şema kısıtlanıyor ve host'un çözümlenen TÜM adresleri denetleniyor.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(400, {"error": "gecersiz_url_semasi",
                                  "detail": "yalnızca http/https"})
    if not parsed.hostname:
        raise HTTPException(400, {"error": "gecersiz_url"})

    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        raise HTTPException(400, {"error": "host_cozumlenemedi",
                                  "host": parsed.hostname})

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise HTTPException(400, {
                "error": "ic_ag_adresi_engellendi",
                "detail": f"{parsed.hostname} -> {ip}",
            })


def _fetch_url(url: str) -> bytes:
    """Boyut sınırlı indirme. Content-Length yalanına karşı akış da sınırlı."""
    if not ALLOW_URL_FETCH:
        raise HTTPException(403, {"error": "url_indirme_kapali"})

    _assert_safe_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": "mockup-engine/1.1"})

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            declared = int(resp.headers.get("Content-Length") or 0)
            if declared > MAX_UPLOAD_BYTES:
                raise HTTPException(413, {"error": "dosya_cok_buyuk",
                                          "limit_mb": MAX_UPLOAD_BYTES // 1048576})
            data = resp.read(MAX_UPLOAD_BYTES + 1)
    except HTTPException:
        raise
    except urllib.error.HTTPError as err:
        raise HTTPException(400, {"error": "url_getirilemedi", "status": err.code})
    except Exception as err:
        raise HTTPException(400, {"error": "url_getirilemedi", "detail": str(err)})

    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, {"error": "dosya_cok_buyuk",
                                  "limit_mb": MAX_UPLOAD_BYTES // 1048576})
    return data


def _decode_base64(payload: str) -> bytes:
    # data:image/png;base64,.... biçimini de kabul et
    if payload.startswith("data:"):
        _, _, payload = payload.partition(",")
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, {"error": "gecersiz_base64"})
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, {"error": "dosya_cok_buyuk"})
    return data


def _validate_image(data: bytes) -> None:
    """Baytların gerçekten çözülebilir bir görüntü olduğunu doğrular.

    Uzantıya veya content-type'a güvenmiyoruz -- ikisi de yalan olabilir.
    """
    if not data:
        raise HTTPException(400, {"error": "bos_dosya"})

    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise HTTPException(400, {
            "error": "gecersiz_gorsel",
            "detail": "dosya PNG/JPG olarak çözülemedi",
        })
    if img.ndim == 3 and img.shape[2] == 4:
        return  # alfa var, ideal
    log.info("tasarımda alfa kanalı yok -- arka plan opak basılacak")


def _transform_quad(quad: list, offset_x: float, offset_y: float,
                    rotate_deg: float) -> list:
    """Baski alanini kaydirir ve merkezi etrafinda dondurur.

    offset degerleri baski alaninin KENDI genisligine gore oranli --
    boylece farkli cozunurlukteki modellerde ayni deger ayni gorsel
    kaymayi veriyor.

    Donus, quad'in kendi merkezinde yapiliyor; boylece kullanicinin
    surukledigi konum korunuyor.
    """
    q = np.array(quad, dtype=np.float64)
    cx, cy = q[:, 0].mean(), q[:, 1].mean()

    # Baski alaninin genisligi olcek birimi olarak kullaniliyor.
    width = float(np.linalg.norm(q[1] - q[0]))

    if rotate_deg:
        a = np.radians(rotate_deg)
        ca, sa = np.cos(a), np.sin(a)
        rel = q - [cx, cy]
        q = np.stack([
            rel[:, 0] * ca - rel[:, 1] * sa,
            rel[:, 0] * sa + rel[:, 1] * ca,
        ], axis=1) + [cx, cy]

    q = q + [offset_x * width, offset_y * width]
    return [[float(x), float(y)] for x, y in q]


def _overrides(scale: float | None, displace: float | None,
               shading: float | None) -> dict[str, Any] | None:
    out: dict[str, Any] = {}
    if scale is not None:
        out["design_scale"] = scale
    if displace is not None:
        out["displacement"] = {"strength": displace}
    if shading is not None:
        out["shading"] = {"strength": shading}
    return out or None


def _placement_override(model_id: str, params) -> dict[str, Any]:
    """offset/rotate verilmisse quad'i donusturup override uretir."""
    ox = params.offset_x or 0.0
    oy = params.offset_y or 0.0
    rot = params.rotate or 0.0
    if not (ox or oy or rot):
        return {}

    meta_path = LIBRARY_DIR / model_id / "meta.json"
    if not meta_path.is_file():
        return {}
    quad = json.loads(meta_path.read_text(encoding="utf-8")).get("print_quad")
    if not quad or len(quad) != 4:
        return {}

    return {"print_quad": _transform_quad(quad, ox, oy, rot)}


def _render_sync(design_path: Path, model_id: str, out_path: Path,
                 color: str | None, overrides: dict | None) -> Path:
    """Executor içinde çalışan senkron iş. Tek gerçek kaynak burası."""
    return generate_mockup(
        design_path=design_path,
        model_id=model_id,
        library_dir=LIBRARY_DIR,
        output_path=out_path,
        overrides=overrides,
        color=color,
    )


async def _render(design_path: Path, model_id: str, out_path: Path,
                  color: str | None, overrides: dict | None) -> Path:
    """CPU işini executor'a atar; olay döngüsü bloklanmaz."""
    assert _slots is not None and _executor is not None
    loop = asyncio.get_running_loop()
    async with _slots:
        return await loop.run_in_executor(
            _executor, _render_sync, design_path, model_id, out_path,
            color, overrides,
        )


def _purge_expired_jobs() -> int:
    """TTL'i geçmiş toplu iş klasörlerini siler."""
    if not JOBS_DIR.is_dir():
        return 0
    cutoff = time.time() - JOB_TTL_SECONDS
    removed = 0
    for entry in JOBS_DIR.iterdir():
        try:
            if entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True) if entry.is_dir() else entry.unlink()
                removed += 1
        except OSError:
            pass
    if removed:
        log.info("%d süresi dolmuş iş temizlendi", removed)
    return removed


def _safe_job_path(job_id: str, filename: str) -> Path:
    """Yol aşımı (path traversal) koruması."""
    job_dir = (JOBS_DIR / job_id).resolve()
    if JOBS_DIR.resolve() not in job_dir.parents and job_dir != JOBS_DIR.resolve():
        raise HTTPException(400, {"error": "gecersiz_job_id"})
    target = (job_dir / filename).resolve()
    if job_dir not in target.parents:
        raise HTTPException(400, {"error": "gecersiz_dosya_adi"})
    return target


# --------------------------------------------------------------------------
# Uç noktalar
# --------------------------------------------------------------------------

# library.REQUIRED_FILES ile ayni liste; /health'te dosya butunlugu
# kontrolu icin gerekiyor.
_ASSET_FILES = ("base.png", "garment_mask.png", "print_mask.png",
                "displace.png", "shading.png", "meta.json")


def _split_by_completeness(model_ids: list[str]) -> tuple[list[str], list[dict]]:
    """Tam ve eksik assetleri ayirir.

    list_models() meta.json'u olan her klasoru donduruyor; bir asset
    yalnizca meta.json ile de listelenebiliyor. Bu, arayuzde
    render edilemeyecek bir modelin secilebilir gorunmesine yol
    aciyordu. /health artik ikisini ayiriyor.
    """
    ready, incomplete = [], []
    for mid in model_ids:
        d = LIBRARY_DIR / mid
        missing = [f for f in _ASSET_FILES if not (d / f).exists()]

        # Dosyalarin varligi yetmiyor: print_quad bos ise render 404
        # veriyor. Eskiden bu model listede "hazir" gorunuyor, ancak
        # RENDER'a basilinca hata aliniyordu.
        reason = None
        if not missing:
            try:
                meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
                quad = meta.get("print_quad")
                if not quad or len(quad) != 4:
                    reason = "print_quad bos -- derive_quad calistirilmali"
            except (json.JSONDecodeError, OSError):
                reason = "meta.json okunamadi"

        if missing or reason:
            incomplete.append({
                "model_id": mid,
                "missing": missing,
                "reason": reason or f"{len(missing)} dosya eksik",
            })
        else:
            ready.append(mid)
    return ready, incomplete


@app.get("/health")
async def health() -> dict:
    models, incomplete = _split_by_completeness(_known_models())
    return {
        "status": "ok" if models else "kutuphane_bos",
        # Arayuz bunlarla kendi surumuyle uyumu kontrol ediyor.
        "api_version": API_VERSION,
        "build": BUILD,
        "pipeline_build": _pipeline_build(),
        "build_ok": _pipeline_build() == BUILD,
        "capabilities": sorted(CAPABILITIES),
        "incomplete": incomplete,
        "version": app.version,
        "library": str(LIBRARY_DIR),
        "models": models,
        "model_count": len(models),
        "colors": list(COLOR_PRESETS),
        "workers": RENDER_WORKERS,
        "max_upload_mb": MAX_UPLOAD_BYTES // 1048576,
        "url_fetch_enabled": ALLOW_URL_FETCH,
    }


@app.get("/colors")
async def colors() -> dict:
    return {"presets": COLOR_PRESETS,
            "custom": "#RRGGBB biçiminde doğrudan da verilebilir"}


@app.post("/render")
async def render(request: Request):
    """Tek mockup üretir.

    İki gövde biçimi kabul edilir:

    multipart/form-data
        design_file=@tasarim.png, model_id, color, scale, displace,
        shading, response_mode

    application/json
        {"design_url": "...", "model_id": "...", "color": "navy"}
        {"design_base64": "iVBOR...", ...}

    response_mode="file" (varsayılan) PNG döner, "json" base64 döner.
    """
    content_type = (request.headers.get("content-type") or "").lower()

    # -- gövdeyi çöz ------------------------------------------------------
    if content_type.startswith("application/json"):
        try:
            raw = await request.json()
        except json.JSONDecodeError:
            raise HTTPException(400, {"error": "gecersiz_json"})
        try:
            params = RenderParams(**raw)
        except Exception as err:
            raise HTTPException(400, {"error": "gecersiz_parametre",
                                      "detail": str(err)})

        if params.design_base64:
            design_bytes = _decode_base64(params.design_base64)
        elif params.design_url:
            design_bytes = _fetch_url(params.design_url)
        else:
            raise HTTPException(400, {
                "error": "tasarim_yok",
                "detail": "design_base64 veya design_url gerekli",
            })

    elif content_type.startswith("multipart/form-data"):
        try:
            form = await request.form()
        except AssertionError as err:
            # starlette, python-multipart kurulu degilse burada
            # AssertionError firlatiyor. Tarayicida bu "Failed to fetch"
            # olarak gorunuyor ve sebebi anlasilmiyor -- acik mesaja
            # ceviriyoruz.
            log.error("form parse edilemedi: %s", err)
            raise HTTPException(500, {
                "error": "form_parse_edilemedi",
                "detail": "python-multipart kurulu degil. Kurulum: "
                          "pip install python-multipart",
            })
        upload = form.get("design_file")

        raw = {k: v for k, v in form.items() if k != "design_file" and v != ""}
        # FormData bool'u "true"/"false" string olarak gonderiyor.
        for flag in ("flip_h", "flip_v"):
            if flag in raw:
                raw[flag] = str(raw[flag]).lower() in ("1", "true", "on", "yes")
        for numeric in ("scale", "displace", "shading",
                        "offset_x", "offset_y", "rotate"):
            if numeric in raw:
                try:
                    raw[numeric] = float(raw[numeric])
                except ValueError:
                    raise HTTPException(400, {"error": "gecersiz_sayi",
                                              "alan": numeric})
        try:
            params = RenderParams(**raw)
        except Exception as err:
            raise HTTPException(400, {"error": "gecersiz_parametre",
                                      "detail": str(err)})

        if upload is not None and hasattr(upload, "read"):
            design_bytes = await upload.read()
            if len(design_bytes) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, {"error": "dosya_cok_buyuk",
                                          "limit_mb": MAX_UPLOAD_BYTES // 1048576})
        elif params.design_url:
            design_bytes = _fetch_url(params.design_url)
        elif params.design_base64:
            design_bytes = _decode_base64(params.design_base64)
        else:
            raise HTTPException(400, {
                "error": "tasarim_yok",
                "detail": "design_file, design_url veya design_base64 gerekli",
            })
    else:
        raise HTTPException(415, {
            "error": "desteklenmeyen_content_type",
            "detail": "multipart/form-data veya application/json kullan",
        })

    _validate_image(design_bytes)
    _assert_model_exists(params.model_id)

    # -- render ------------------------------------------------------------
    # Geçici klasör: işlem bitince BackgroundTask ile silinir.
    overrides = _overrides(params.scale, params.displace, params.shading) or {}

    # Konumlandirma istendi ama pipeline destekliyorsa uygula, yoksa
    # SESSIZCE YOK SAYMA -- acik hata ver.
    if (params.offset_x or params.offset_y or params.rotate):
        if "placement" not in CAPABILITIES:
            raise HTTPException(500, {
                "error": "pipeline_eski",
                "detail": "mockup_engine/pipeline.py quad override desteklemiyor. "
                          "Konumlandirma (offset/rotate) calismaz. "
                          "pipeline.py dosyasini guncelle ve uvicorn'u yeniden baslat.",
            })
        overrides.update(_placement_override(params.model_id, params))

    workdir = Path(tempfile.mkdtemp(prefix="mockup_"))
    design_path = workdir / "design.png"
    if params.flip_h or params.flip_v:
        # IMREAD_UNCHANGED alfa kanalini korur -- baski tasarimlarinin
        # neredeyse tamami seffaf arka planli.
        img = cv2.imdecode(np.frombuffer(design_bytes, np.uint8),
                           cv2.IMREAD_UNCHANGED)
        if img is None:
            shutil.rmtree(workdir, ignore_errors=True)
            raise HTTPException(400, {"error": "gecersiz_gorsel"})
        if params.flip_h:
            img = cv2.flip(img, 1)
        if params.flip_v:
            img = cv2.flip(img, 0)
        ok, buf = cv2.imencode(".png", img)
        if not ok:
            shutil.rmtree(workdir, ignore_errors=True)
            raise HTTPException(500, {"error": "cevirme_basarisiz"})
        design_path.write_bytes(buf.tobytes())
    else:
        design_path.write_bytes(design_bytes)
    out_path = workdir / "mockup.png"

    started = time.perf_counter()
    try:
        await _render(design_path, params.model_id, out_path,
                      params.color, overrides or None)
    except LibraryError as err:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(404, {"error": "model_yuklenemedi", "detail": str(err)})
    except ValueError as err:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(400, {"error": "render_parametresi_gecersiz",
                                  "detail": str(err)})
    except Exception as err:
        shutil.rmtree(workdir, ignore_errors=True)
        log.exception("render hatası")
        raise HTTPException(500, {"error": "render_basarisiz", "detail": str(err)})

    elapsed_ms = round((time.perf_counter() - started) * 1000)

    # Sunucunun GERCEKTEN aldigi ayarlar. Arayuzde gorunuyor; boylece
    # "ayari degistirdim ama render ayni" durumunda parametrenin
    # sunucuya ulasip ulasmadigi tahmin edilmiyor, GORULUYOR.
    applied = {
        "scale": params.scale,
        "displace": params.displace,
        "shading": params.shading,
        "color": params.color,
        "offset_x": params.offset_x,
        "offset_y": params.offset_y,
        "rotate": params.rotate,
        "flip_h": params.flip_h,
        "flip_v": params.flip_v,
        "quad_override": bool(overrides.get("print_quad")),
    }
    applied = {k: v for k, v in applied.items() if v not in (None, False)}
    applied_str = json.dumps(applied, ensure_ascii=False)

    log.info("render %s %dms %s", params.model_id, elapsed_ms, applied_str)

    if params.response_mode == "json":
        payload = base64.b64encode(out_path.read_bytes()).decode()
        shutil.rmtree(workdir, ignore_errors=True)
        return JSONResponse({
            "status": "ok",
            "model_id": params.model_id,
            "color": params.color,
            "elapsed_ms": elapsed_ms,
            "applied": applied,
            "image_base64": payload,
            "media_type": "image/png",
        })

    # FileResponse dosyayı yanıt gönderildikten SONRA okur; bu yüzden
    # temizlik BackgroundTask ile yanıtın ardına bağlanıyor.
    return FileResponse(
        out_path,
        media_type="image/png",
        filename=f"{params.model_id.replace('/', '_')}"
                 f"{'-' + params.color if params.color else ''}.png",
        headers={"X-Render-Ms": str(elapsed_ms),
                 "X-Applied": applied_str,
                 "Access-Control-Expose-Headers": "X-Render-Ms, X-Applied"},
        background=BackgroundTask(shutil.rmtree, workdir, ignore_errors=True),
    )


@app.post("/batch-render")
async def batch_render(params: BatchParams):
    """Model × renk matrisini toplu üretir.

        {"design_url": "...",
         "model_ids": ["test-model"],
         "colors": ["white", "black", "navy"]}

    Çıktılar sunucuda saklanır; yanıt indirme bağlantılarını içerir.
    """
    if params.design_base64:
        design_bytes = _decode_base64(params.design_base64)
    elif params.design_url:
        design_bytes = _fetch_url(params.design_url)
    else:
        raise HTTPException(400, {"error": "tasarim_yok",
                                  "detail": "design_base64 veya design_url gerekli"})

    _validate_image(design_bytes)

    items = params.resolve_items()
    if not items:
        raise HTTPException(400, {"error": "bos_istek"})
    if len(items) > MAX_BATCH_ITEMS:
        raise HTTPException(400, {
            "error": "toplu_istek_cok_buyuk",
            "istenen": len(items),
            "limit": MAX_BATCH_ITEMS,
        })

    for item in items:
        _assert_model_exists(item.model_id)
        if item.color:
            c = item.color.strip().lower()
            if c not in COLOR_PRESETS and not (c.startswith("#") and len(c) == 7):
                raise HTTPException(400, {"error": "gecersiz_renk", "renk": item.color})

    _purge_expired_jobs()

    job_id = uuid.uuid4().hex[:16]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    design_path = job_dir / "_design.png"
    design_path.write_bytes(design_bytes)

    overrides = _overrides(params.scale, params.displace, params.shading)
    started = time.perf_counter()

    async def one(item: BatchItem) -> dict:
        safe_model = item.model_id.replace("/", "_")
        name = f"{safe_model}{'-' + item.color if item.color else ''}.png"
        try:
            await _render(design_path, item.model_id, job_dir / name,
                          item.color, overrides)
            return {"model_id": item.model_id, "color": item.color,
                    "filename": name, "url": f"/outputs/{job_id}/{name}",
                    "ok": True}
        except Exception as err:
            log.warning("toplu render başarısız %s/%s: %s",
                        item.model_id, item.color, err)
            return {"model_id": item.model_id, "color": item.color,
                    "ok": False, "error": str(err)}

    results = await asyncio.gather(*(one(i) for i in items))
    design_path.unlink(missing_ok=True)

    ok = [r for r in results if r["ok"]]

    if ok:
        with zipfile.ZipFile(job_dir / "_bundle.zip", "w",
                             zipfile.ZIP_DEFLATED) as zf:
            for r in ok:
                zf.write(job_dir / r["filename"], r["filename"])

    return {
        "status": "ok" if len(ok) == len(results) else "kismi",
        "job_id": job_id,
        "requested": len(results),
        "succeeded": len(ok),
        "failed": len(results) - len(ok),
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
        "zip_url": f"/outputs/{job_id}.zip" if ok else None,
        "expires_in_seconds": JOB_TTL_SECONDS,
        "results": results,
    }


class QuadSave(BaseModel):
    """Arayuzden gelen kalici quad kaydi."""
    offset_x: float = Field(0.0, ge=-6.0, le=6.0)
    offset_y: float = Field(0.0, ge=-6.0, le=6.0)
    rotate: float = Field(0.0, ge=-180.0, le=180.0)
    design_scale: float | None = Field(None, gt=0, le=3.0)


@app.post("/models/{model_id:path}/quad")
async def save_quad(model_id: str, body: QuadSave) -> dict:
    """Yerlestirmeyi meta.json'a KALICI olarak yazar.

    Arayuzde deneme yanilmayla bulunan konum, bir sonraki render'da
    varsayilan olsun diye. print_quad guncelleniyor ve quad_source
    "manual-ui" olarak isaretleniyor -- sonradan bu quad'in nereden
    geldigi anlasilabilsin.

    DIKKAT: print_mask.png diskte eski quad'dan uretilmis durumda.
    Kaydettikten sonra yenilenmesi gerekiyor:
        python tools/prepare_base.py <model> --force
    Yanit bunu hatirlatiyor.
    """
    if model_id not in _known_models():
        raise HTTPException(404, {"error": "model_bulunamadi", "model_id": model_id})

    d = (LIBRARY_DIR / model_id).resolve()
    if LIBRARY_DIR.resolve() not in d.parents:
        raise HTTPException(400, {"error": "gecersiz_model_id"})

    meta_path = d / "meta.json"
    if not meta_path.is_file():
        raise HTTPException(404, {"error": "meta_yok"})

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    quad = meta.get("print_quad")
    if not quad or len(quad) != 4:
        raise HTTPException(400, {"error": "print_quad_yok"})

    new_quad = _transform_quad(quad, body.offset_x, body.offset_y, body.rotate)
    new_quad = [[int(round(x)), int(round(y))] for x, y in new_quad]

    meta["print_quad"] = new_quad
    meta["quad_source"] = "manual-ui"
    if body.design_scale is not None:
        meta["design_scale"] = round(body.design_scale, 3)

    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    log.info("quad kaydedildi %s -> %s", model_id, new_quad)

    return {
        "status": "ok",
        "model_id": model_id,
        "print_quad": new_quad,
        "design_scale": meta.get("design_scale"),
        "uyari": "print_mask.png hala eski quad'dan. Yenile: "
                 f"python tools/prepare_base.py {model_id} --force",
    }


@app.get("/selftest")
async def selftest() -> dict:
    """Konumlandirmanin GERCEKTEN calisip calismadigini olcer.

    Uzaktan teshis yerine kullanicinin kendi makinesinde kanit
    uretiyor: ayni tasarimi farkli offset degerleriyle render edip
    basilan bolgenin merkezini karsilastiriyor.

    Tarayicida acilabilir:  http://127.0.0.1:8090/selftest
    """
    models, _ = _split_by_completeness(_known_models())
    if not models:
        raise HTTPException(400, {"error": "model_yok"})

    design = ROOT / "tasarimlar" / "test-design.png"
    if not design.is_file():
        raise HTTPException(400, {"error": "test_tasarimi_yok",
                                  "detail": str(design)})

    model_id = models[0]
    base = cv2.imread(str(LIBRARY_DIR / model_id / "base.png"), cv2.IMREAD_COLOR)
    if base is None:
        raise HTTPException(500, {"error": "base_okunamadi"})

    olcumler = []
    with tempfile.TemporaryDirectory(prefix="selftest_") as tmp:
        for oy in (0.0, 0.3, 0.6):
            out = Path(tmp) / f"t{oy}.png"
            ov = {"print_quad": _transform_quad(
                json.loads((LIBRARY_DIR / model_id / "meta.json")
                           .read_text(encoding="utf-8"))["print_quad"],
                0.0, oy, 0.0)} if oy else None

            _render_sync(design, model_id, out, None, ov)

            img = cv2.imread(str(out), cv2.IMREAD_COLOR)
            diff = np.abs(img.astype(np.int16) - base.astype(np.int16)).max(axis=2) > 3
            ys, _xs = np.where(diff)
            olcumler.append({
                "offset_y": oy,
                "merkez_y": int((ys.min() + ys.max()) // 2) if len(ys) else None,
            })

    merkezler = [m["merkez_y"] for m in olcumler]
    calisiyor = (None not in merkezler
                 and merkezler[0] < merkezler[1] < merkezler[2])

    return {
        "sonuc": "KONUMLANDIRMA CALISIYOR" if calisiyor
                 else "KONUMLANDIRMA CALISMIYOR",
        "calisiyor": calisiyor,
        "model": model_id,
        "olcumler": olcumler,
        "aciklama": (
            "offset_y arttikca merkez_y de artmali."
            if calisiyor else
            "merkez_y degismiyor: mockup_engine/pipeline.py eski olabilir. "
            "BUILD damgalarini karsilastir."
        ),
        "build": BUILD,
        "pipeline_build": _pipeline_build(),
        "build_ok": _pipeline_build() == BUILD,
    }


@app.get("/models/{model_id:path}/meta")
async def model_meta(model_id: str) -> dict:
    """Yerlestirme tuvalinin ihtiyac duydugu geometri.

    print_quad ve base gorselin piksel boyutlari. Arayuz bunlarla
    tasarimi dogru oranda ve dogru yerde gosteriyor.
    """
    if model_id not in _known_models():
        raise HTTPException(404, {"error": "model_bulunamadi", "model_id": model_id})

    d = (LIBRARY_DIR / model_id).resolve()
    if LIBRARY_DIR.resolve() not in d.parents:
        raise HTTPException(400, {"error": "gecersiz_model_id"})

    meta_path = d / "meta.json"
    base_path = d / "base.png"
    if not meta_path.is_file() or not base_path.is_file():
        raise HTTPException(404, {"error": "asset_eksik", "model_id": model_id})

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    img = cv2.imread(str(base_path), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(500, {"error": "base_okunamadi"})

    # Giysinin yatay merkezi -- arayuzdeki dikey kilavuz bunu kullaniyor.
    # Baski alaninin merkezi degil: baski gogus hizasinda ve tisortun
    # tam ortasinda olmayabilir, kullanici "ortada mi" derken giysiyi
    # kastediyor.
    garment_cx = None
    gm_path = d / "garment_mask.png"
    if gm_path.is_file():
        gm = cv2.imread(str(gm_path), cv2.IMREAD_GRAYSCALE)
        if gm is not None and gm.shape[:2] == img.shape[:2]:
            ys, xs = np.where(gm > 127)
            if len(xs):
                # Govde bandinin medyani -- kollar simetrik olmayabilir.
                y0, y1 = int(ys.min()), int(ys.max())
                lo = int(y0 + (y1 - y0) * 0.45)
                hi = int(y0 + (y1 - y0) * 0.75)
                cols = []
                for yy in range(lo, max(lo + 1, hi)):
                    row = np.where(gm[yy] > 127)[0]
                    if len(row):
                        cols.append(float(row.mean()))
                if cols:
                    garment_cx = float(np.median(cols))

    return {
        "model_id": model_id,
        "width": int(img.shape[1]),
        "height": int(img.shape[0]),
        "garment_cx": garment_cx,
        "print_quad": meta.get("print_quad"),
        "design_scale": meta.get("design_scale"),
        "asset_type": meta.get("asset_type"),
        "quad_source": meta.get("quad_source"),
        "publishable": meta.get("publishable"),
    }


@app.get("/models/{model_id:path}/preview")
async def model_preview(model_id: str, w: int = 640):
    """Base modelin onizleme gorseli.

    Arayuzde hangi tisortun secildigini gostermek icin. Tam cozunurluk
    gereksiz -- varsayilan 640 px genislige kuculterek gonderiyoruz.
    Render cikitisi bundan etkilenmiyor; bu yalnizca onizleme.
    """
    if model_id not in _known_models():
        raise HTTPException(404, {"error": "model_bulunamadi", "model_id": model_id})

    # Yol asimi korumasi: model_id kullanicidan geliyor ve "/" iceriyor.
    base = (LIBRARY_DIR / model_id / "base.png").resolve()
    if LIBRARY_DIR.resolve() not in base.parents:
        raise HTTPException(400, {"error": "gecersiz_model_id"})
    if not base.is_file():
        raise HTTPException(404, {"error": "base_png_yok", "model_id": model_id})

    img = cv2.imread(str(base), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(500, {"error": "onizleme_okunamadi"})

    w = max(120, min(int(w), 1600))
    if img.shape[1] > w:
        scale = w / img.shape[1]
        img = cv2.resize(img, (w, int(round(img.shape[0] * scale))),
                         interpolation=cv2.INTER_AREA)

    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    if not ok:
        raise HTTPException(500, {"error": "onizleme_kodlanamadi"})

    return Response(content=buf.tobytes(), media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=300"})


@app.get("/outputs/{job_id}.zip")
async def download_zip(job_id: str):
    path = _safe_job_path(job_id, "_bundle.zip")
    if not path.is_file():
        raise HTTPException(404, {"error": "job_bulunamadi", "job_id": job_id})
    return FileResponse(path, media_type="application/zip",
                        filename=f"mockups-{job_id}.zip")


@app.get("/outputs/{job_id}/{filename}")
async def download_output(job_id: str, filename: str):
    path = _safe_job_path(job_id, filename)
    if not path.is_file():
        raise HTTPException(404, {"error": "dosya_bulunamadi"})
    return FileResponse(path, media_type="image/png", filename=filename)


# --------------------------------------------------------------------------
# Arayuz
# --------------------------------------------------------------------------
# web/ klasoru ayni sunucudan servis ediliyor. Boylece:
#   - tek port, tek komut
#   - arayuz ile API ayni origin -> CORS sorunu yok
#   - app.js'te port numarasi SABIT KODLANMIYOR
#
# Onceden iki ayri sunucu vardi (uvicorn + http.server) ve portlari elle
# eslestirmek gerekiyordu; API 8090'a tasindiginda app.js hala 8080'i
# ariyordu.
#
# Mount EN SONDA: "/" tum yollari yakalar, API uclarindan once
# tanimlanirsa onlari golgeler.
WEB_DIR = ROOT / "web"
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    log.info("arayuz: %s", WEB_DIR)
else:
    log.warning("web/ klasoru yok, arayuz servis edilmiyor: %s", WEB_DIR)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8080, reload=True)
