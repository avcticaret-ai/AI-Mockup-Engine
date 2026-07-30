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
from fastapi.responses import FileResponse, JSONResponse
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
)


# --------------------------------------------------------------------------
# Şemalar
# --------------------------------------------------------------------------

class RenderParams(BaseModel):
    """POST /render gövdesi (JSON kullanıldığında)."""

    design_url: str | None = None
    design_base64: str | None = None
    model_id: str = "test-model"
    color: str | None = None
    scale: float | None = Field(None, gt=0, le=2.0)
    displace: float | None = Field(None, ge=0, le=200)
    shading: float | None = Field(None, ge=0, le=1)
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

    scale: float | None = Field(None, gt=0, le=2.0)
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

@app.get("/health")
async def health() -> dict:
    models = _known_models()
    return {
        "status": "ok" if models else "kutuphane_bos",
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
        form = await request.form()
        upload = form.get("design_file")

        raw = {k: v for k, v in form.items() if k != "design_file" and v != ""}
        for numeric in ("scale", "displace", "shading"):
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
    workdir = Path(tempfile.mkdtemp(prefix="mockup_"))
    design_path = workdir / "design.png"
    design_path.write_bytes(design_bytes)
    out_path = workdir / "mockup.png"

    started = time.perf_counter()
    try:
        await _render(design_path, params.model_id, out_path,
                      params.color, _overrides(params.scale, params.displace,
                                               params.shading))
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
    log.info("render %s color=%s %dms", params.model_id, params.color, elapsed_ms)

    if params.response_mode == "json":
        payload = base64.b64encode(out_path.read_bytes()).decode()
        shutil.rmtree(workdir, ignore_errors=True)
        return JSONResponse({
            "status": "ok",
            "model_id": params.model_id,
            "color": params.color,
            "elapsed_ms": elapsed_ms,
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
        headers={"X-Render-Ms": str(elapsed_ms)},
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8080, reload=True)
