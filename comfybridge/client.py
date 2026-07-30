"""ComfyUI HTTP API istemcisi.

Sadece standart kutuphane kullaniyor -- requests bagimliligi yok, boylece
hem mockup motorunun venv'inde hem de ComfyUI'in kendi venv'inde calisir.

ComfyUI API yuzeyi:
    POST /prompt          is akisini kuyruga at   -> {"prompt_id": "..."}
    GET  /history/{id}    sonucu sorgula          -> {"outputs": {...}}
    GET  /view?...        uretilen goruntuyu indir
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path


class ComfyError(Exception):
    """ComfyUI ile iletisim veya calistirma hatasi."""


@dataclass
class GeneratedImage:
    filename: str
    subfolder: str
    type: str
    data: bytes


class ComfyClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 8188, timeout: int = 30):
        self.base = f"http://{host}:{port}"
        self.timeout = timeout
        self.client_id = str(uuid.uuid4())

    # -- dusuk seviye ------------------------------------------------------

    def _get(self, path: str) -> bytes:
        try:
            with urllib.request.urlopen(self.base + path, timeout=self.timeout) as r:
                return r.read()
        except urllib.error.URLError as err:
            raise ComfyError(
                f"ComfyUI'a ulasilamadi ({self.base}). Calisiyor mu?\n  {err}"
            ) from err

    def _post_json(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base + path, data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")
            # ComfyUI dogrulama hatalarini burada JSON olarak donuyor --
            # cogu zaman eksik model veya yanlis node adi anlamina gelir.
            raise ComfyError(f"ComfyUI is akisini reddetti (HTTP {err.code}):\n{detail}") from err
        except urllib.error.URLError as err:
            raise ComfyError(f"ComfyUI'a ulasilamadi ({self.base}): {err}") from err

    # -- yuksek seviye -----------------------------------------------------

    def ping(self) -> bool:
        """ComfyUI ayakta mi."""
        try:
            self._get("/system_stats")
            return True
        except ComfyError:
            return False

    def object_info(self) -> dict:
        return json.loads(self._get("/object_info"))

    def missing_node_types(self, workflow: dict) -> list[str]:
        """Is akisindaki node'lardan bu kurulumda OLMAYANLARI dondurur.

        Kuyruga atmadan once cagirmak, 'neden hicbir sey olmuyor' turu
        hata ayiklamalarini tamamen ortadan kaldiriyor.
        """
        available = set(self.object_info().keys())
        needed = {n["class_type"] for n in workflow.values() if "class_type" in n}
        return sorted(needed - available)

    def queue(self, workflow: dict) -> str:
        result = self._post_json("/prompt", {
            "prompt": workflow,
            "client_id": self.client_id,
        })
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            raise ComfyError(f"prompt_id donmedi: {result}")
        return prompt_id

    def wait(self, prompt_id: str, poll: float = 1.0, timeout: float = 600.0) -> dict:
        """Uretim bitene kadar bekler ve history kaydini dondurur."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            history = json.loads(self._get(f"/history/{prompt_id}"))
            if prompt_id in history:
                entry = history[prompt_id]
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise ComfyError(f"Uretim hata verdi:\n{json.dumps(status, indent=2)}")
                if entry.get("outputs"):
                    return entry
            time.sleep(poll)
        raise ComfyError(f"{timeout:.0f} saniyede tamamlanmadi: {prompt_id}")

    def fetch_images(self, history_entry: dict) -> list[GeneratedImage]:
        images: list[GeneratedImage] = []
        for node_output in history_entry.get("outputs", {}).values():
            for img in node_output.get("images", []):
                query = urllib.parse.urlencode({
                    "filename": img["filename"],
                    "subfolder": img.get("subfolder", ""),
                    "type": img.get("type", "output"),
                })
                images.append(GeneratedImage(
                    filename=img["filename"],
                    subfolder=img.get("subfolder", ""),
                    type=img.get("type", "output"),
                    data=self._get(f"/view?{query}"),
                ))
        return images

    def run(self, workflow: dict, timeout: float = 600.0) -> list[GeneratedImage]:
        """Kuyruga at, bekle, goruntuleri indir."""
        return self.fetch_images(self.wait(self.queue(workflow), timeout=timeout))


# -- is akisi yardimcilari -------------------------------------------------

def load_workflow(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def apply(workflow: dict, node_id: str, **inputs) -> dict:
    """Is akisinin bir kopyasini dondurur, verilen node girdilerini ezer.

    Sablonu yerinde degistirmiyoruz -- toplu uretimde ayni sablondan
    onlarca varyant turetiliyor, mutasyon sizintisi kotu hata olurdu.
    """
    clone = json.loads(json.dumps(workflow))
    if node_id not in clone:
        raise ComfyError(f"Is akisinda '{node_id}' node'u yok.")
    clone[node_id]["inputs"].update(inputs)
    return clone


def validate_links(workflow: dict) -> list[str]:
    """Baglanti butunlugunu kontrol eder. ComfyUI'a gitmeden calisir."""
    problems: list[str] = []
    for node_id, node in workflow.items():
        for key, value in node.get("inputs", {}).items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                target = value[0]
                if target not in workflow:
                    problems.append(
                        f"node {node_id}.{key} -> olmayan node '{target}'"
                    )
    return problems
