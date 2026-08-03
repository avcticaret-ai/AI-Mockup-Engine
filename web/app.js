/* Sozdizimi veya calisma zamani hatasi sayfayi SESSIZCE olduruyordu:
 * status "sunucu bekleniyor" da takili kaliyor, listeler bos kaliyor,
 * hicbir hata gorunmuyordu. Artik ekranda gorunuyor. */
window.addEventListener("error", (e) => {
  const box = document.getElementById("error");
  const st = document.getElementById("status");
  if (st) { st.textContent = "arayüz hatası"; st.className = "status status--err"; }
  if (box) {
    box.hidden = false;
    box.textContent =
      "ARAYÜZ HATASI\n\n" +
      `${e.message}\n` +
      `${e.filename || ""}:${e.lineno || "?"}:${e.colno || "?"}\n\n` +
      "app.js düzenlendiyse geri al veya paketten temiz kopyayı kur.\n" +
      "Ayrıntı için F12 → Console.";
  }
});

/* AI Mockup Studio -- yerel arayuz.
 *
 * Hicbir goruntu isleme mantigi ICERMEZ. Tek isi dosyayi ve ayarlari
 * FastAPI'ye gondermek, donen PNG'yi gostermek. Compositor, recolor ve
 * kutuphane mantigi tek yerde (motorda) kalir -- arayuz ile CLI birebir
 * ayni ciktiyi uretir.
 */

/* API adresi SABIT KODLANMIYOR.
 *
 * Sunucu artik web/ klasorunu de servis ediyor, yani arayuz ile API
 * ayni origin'de. Port ne olursa olsun (8080, 8090, ...) adres kendi
 * kendine dogru cikiyor.
 *
 * Eskiden burada "http://127.0.0.1:8080" yaziyordu ve sunucu baska bir
 * porta tasindiginda arayuz yanlis adresi ariyordu.
 *
 * Ayri bir sunucudan aciyorsan (or. file:// veya baska port) su iki
 * yoldan biriyle ezebilirsin:
 *     http://.../index.html?api=http://127.0.0.1:8090
 *     localStorage.setItem("mockup-api", "http://127.0.0.1:8090")
 */
const API = (() => {
  const q = new URLSearchParams(location.search).get("api");
  if (q) return q.replace(/\/$/, "");
  try {
    const saved = localStorage.getItem("mockup-api");
    if (saved) return saved.replace(/\/$/, "");
  } catch { /* localStorage kapali */ }
  if (location.protocol === "http:" || location.protocol === "https:") {
    return location.origin;
  }
  // file:// ile acildiysa tahmin etmek zorundayiz
  return "http://127.0.0.1:8080";
})();
const BUILD = "2026.08.03-3";
const LS_KEY = "mockup-studio-prefs";
const HISTORY_MAX = 8;

/* Sunucudaki offset siniriyla AYNI olmali. Farkli olursa kullanici
 * tuvalde tasiyabildigi bir konumda HTTP 400 aliyor. */
const OFFSET_LIMIT = 6.0;

/* Arayuzun calismak icin ihtiyac duydugu sunucu yetenekleri.
 * Eksikse kullaniciyi acikca uyariyoruz -- eskiden sunucu bilmedigi
 * parametreyi SESSIZCE yok sayiyordu ve "degisiklik yansimiyor"
 * seklinde gorunuyordu. */
const NEEDED_CAPS = ["render", "preview", "meta", "placement", "flip", "scale3", "quad_save"];

/* Eksik yetenek -> ne yapilmasi gerektigi. Genel "sunucu eski" mesaji
 * hangi DOSYANIN eski oldugunu soylemiyordu. */
const CAP_FIX = {
  placement: "mockup_engine/pipeline.py ESKI — konumlandırma (sürükle/döndür) çalışmaz",
  flip: "server.py eski — aynalama çalışmaz",
  scale3: "server.py eski — ölçek 2.0 ile sınırlı",
  quad_save: "server.py eski — meta.json'a kaydet çalışmaz",
  preview: "server.py eski — model önizlemesi yok",
  meta: "server.py eski — yerleştirme tuvali çalışmaz",
};

const el = (id) => document.getElementById(id);

const dom = {
  status: el("status"),
  drop: el("drop"),
  dropText: el("dropText"),
  designPreview: el("designPreview"),
  file: el("file"),
  designInfo: el("designInfo"),
  models: el("models"),
  modelPreview: el("modelPreview"),
  modelPreviewWrap: el("modelPreviewWrap"),
  modelInfo: el("modelInfo"),
  incompleteInfo: el("incompleteInfo"),
  color: el("color"),
  render: el("render"),
  error: el("error"),
  stage: el("stage"),
  stageEmpty: el("stageEmpty"),
  result: el("result"),
  busy: el("busy"),
  meta: el("meta"),
  download: el("download"),
  reset: el("resetTuning"),
  viewResult: el("viewResult"),
  viewBase: el("viewBase"),
  zoomIn: el("zoomIn"),
  zoomOut: el("zoomOut"),
  zoomFit: el("zoomFit"),
  zoomLabel: el("zoomLabel"),
  history: el("history"),
  historyWrap: el("historyWrap"),
  clearHistory: el("clearHistory"),
  placeWrap: el("placeWrap"),
  placeCanvas: el("placeCanvas"),
  placeBase: el("placeBase"),
  placeQuad: el("placeQuad"),
  placeDesign: el("placeDesign"),
  placeDesignImg: el("placeDesignImg"),
  placeRot: el("placeRot"),
  placeReset: el("placeReset"),
  roX: el("roX"), roY: el("roY"), roR: el("roR"), roS: el("roS"),
  placeSave: el("placeSave"),
  autoRender: el("autoRender"),
  guideV: el("guideV"),
  guideH: el("guideH"),
  stale: el("stale"),
};

const TUNING = [
  { id: "scale", out: "scaleOut", off: 0, fmt: (v) => v.toFixed(2) },
  { id: "displace", out: "displaceOut", off: -1, fmt: (v) => v.toFixed(0) },
  { id: "shading", out: "shadingOut", off: -0.04, fmt: (v) => v.toFixed(2) },
];

const FLATLAY_RE = /(^|\/)flatlay(\/|-|$)/;

let designFile = null;
let designUrl = null;
let resultUrl = null;
let serverInfo = "";
let zoom = 0;                 // 0 = sigdir
let view = "result";
let history = [];
let inflight = null;   // suren render'in AbortController'i
let flipH = false;
let flipV = false;

// Yerlestirme durumu. offset degerleri baski alani GENISLIGININ orani
// cinsinden -- sunucu da ayni birimi kullaniyor, boylece farkli
// cozunurlukteki modellerde ayni deger ayni gorsel kaymayi veriyor.
const place = { x: 0, y: 0, rot: 0, quad: null, baseW: 0, baseH: 0 };

// --------------------------------------------------------------------
// Durum
// --------------------------------------------------------------------

function setStatus(text, kind) {
  dom.status.textContent = text;
  dom.status.className = `status status--${kind}`;
}

function showError(message) {
  dom.error.textContent = message;
  dom.error.hidden = false;
}

function clearError() { dom.error.hidden = true; }

function updateRenderButton() {
  dom.render.disabled = !(designFile && dom.models.value);
}

// --------------------------------------------------------------------
// Tercih hafizasi
// --------------------------------------------------------------------

function savePrefs() {
  try {
    const tuning = {};
    TUNING.forEach(({ id }) => { tuning[id] = el(id).value; });
    localStorage.setItem(LS_KEY, JSON.stringify({
      model: dom.models.value,
      color: dom.color.value,
      tuning,
      place: { x: place.x, y: place.y, rot: place.rot },
      flip: { h: flipH, v: flipV },
      auto: dom.autoRender.checked,
    }));
  } catch { /* localStorage kapaliysa sessizce gec */ }
}

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; }
  catch { return {}; }
}

// --------------------------------------------------------------------
// Sunucu
// --------------------------------------------------------------------

async function connect() {
  try {
    const res = await fetch(`${API}/health`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const prefs = loadPrefs();

    // Duz tisort ve flatlay ayri gruplarda. Flatlay ikinci faz konusu;
    // gruplamak yanlislikla secilmesini onluyor.
    dom.models.innerHTML = "";
    const groups = { flat: [], flatlay: [], other: [] };
    (data.models || []).forEach((m) => {
      if (FLATLAY_RE.test(m)) groups.flatlay.push(m);
      else if (m === "test-model") groups.other.push(m);
      else groups.flat.push(m);
    });

    const addGroup = (label, items) => {
      if (!items.length) return;
      const g = document.createElement("optgroup");
      g.label = label;
      items.forEach((m) => {
        const o = document.createElement("option");
        o.value = m;
        o.textContent = m;
        g.appendChild(o);
      });
      dom.models.appendChild(g);
    };

    addGroup("Düz tişört", groups.flat);
    addGroup("Sentetik / test", groups.other);
    addGroup("Flatlay (faz 2)", groups.flatlay);

    dom.color.innerHTML = "";
    const none = document.createElement("option");
    none.value = "";
    none.textContent = "(değiştirme)";
    dom.color.appendChild(none);
    (data.colors || []).forEach((c) => {
      const o = document.createElement("option");
      o.value = c;
      o.textContent = c;
      dom.color.appendChild(o);
    });

    if (!data.models || data.models.length === 0) {
      setStatus("kütüphane boş", "err");
      showError(
        "Sunucu çalışıyor ama kullanılabilir base model yok.\n" +
        "Önce bir asset üret:\n" +
        "  python tools\\build_asset.py foto.png --model <id>"
      );
      return;
    }

    // Son kullanilan model hala varsa onu sec, yoksa ilk duz tisort.
    if (prefs.model && data.models.includes(prefs.model)) {
      dom.models.value = prefs.model;
    } else if (groups.flat.length) {
      dom.models.value = groups.flat[0];
    }
    if (prefs.color) dom.color.value = prefs.color;
    if (typeof prefs.auto === "boolean") dom.autoRender.checked = prefs.auto;
    if (prefs.flip) {
      flipH = !!prefs.flip.h;
      flipV = !!prefs.flip.v;
      applyFlipPreview();
    }
    if (prefs.place) {
      place.x = prefs.place.x || 0;
      place.y = prefs.place.y || 0;
      place.rot = prefs.place.rot || 0;
    }
    if (prefs.tuning) {
      TUNING.forEach(({ id, out, off, fmt }) => {
        const v = prefs.tuning[id];
        if (v === undefined) return;
        el(id).value = v;
        const n = parseFloat(v);
        el(out).textContent = n > off ? fmt(n) : "meta.json";
        el(out).classList.toggle("is-set", n > off);
      });
    }

    // BUILD damgasi karsilastirmasi -- en kesin uyumsuzluk tespiti.
    // Ayni pakettan gelen dosyalarin damgasi aynidir; biri eskiyse
    // hemen belli oluyor ve HANGISI oldugu yaziyor.
    const sb = data.build || "?";
    const pb = data.pipeline_build || "?";
    if (sb !== BUILD || pb !== BUILD) {
      setStatus("dosyalar uyumsuz", "err");
      const rows = [
        ["web/app.js", BUILD],
        ["server.py", sb],
        ["mockup_engine/pipeline.py", pb],
      ];
      showError(
        "DOSYA SÜRÜMLERİ UYUMSUZ\n\n" +
        rows.map(([f, b]) =>
          `${b === BUILD ? "  ✓" : "  ✗"} ${f.padEnd(28)} ${b}`).join("\n") +
        "\n\n✗ işaretli dosyaları paketten kopyala.\n" +
        "Sonra UVICORN'U YENİDEN BAŞLAT — çalışan sürece\n" +
        "yeni kod yüklenmiyor.\n\n" +
        "Hepsi ✓ olana kadar konumlandırma çalışmaz."
      );
      return;
    }

    // Yetenek kontrolu
    const caps = data.capabilities || [];
    const missing = NEEDED_CAPS.filter((c) => !caps.includes(c));
    if (missing.length) {
      setStatus("sunucu eski", "err");
      showError(
        "SUNUCU DOSYALARI ESKİ.\n\n" +
        missing.map((c) => `· ${CAP_FIX[c] || c}`).join("\n") +
        `\n\nSunucu sürümü: ${data.api_version || "bilinmiyor"}\n\n` +
        "Eksik dosyaları güncelle, sonra uvicorn'u YENİDEN BAŞLAT.\n" +
        "Çalışan sürece yeni kod yüklenmiyor."
      );
      return;
    }

    setStatus(`bağlı · ${data.models.length} model`, "ok");
    serverInfo = `${data.workers} worker · max ${data.max_upload_mb} MB · build ${data.build}`;

    // Eksik assetler /health tarafindan ayriliyor; secilemezler ama
    // kullanicinin bunlarin var oldugunu bilmesi gerekiyor.
    const inc = data.incomplete || [];
    // Sebebi de goster -- "tamamlanmamis" tek basina ne yapilacagini
    // soylemiyor. print_quad eksikse derive_quad calistirilmali.
    dom.incompleteInfo.innerHTML = "";
    if (inc.length) {
      const head = document.createElement("div");
      head.textContent = `${inc.length} asset tamamlanmamış:`;
      dom.incompleteInfo.appendChild(head);
      inc.forEach((i) => {
        const line = document.createElement("div");
        line.textContent = `· ${i.model_id} — ${i.reason || "eksik"}`;
        dom.incompleteInfo.appendChild(line);
      });
    }

    onModelChange();
    clearError();
    updateRenderButton();
  } catch {
    setStatus("sunucuya ulaşılamıyor", "err");
    showError(
      `${API} yanıt vermiyor.\n\nSunucuyu başlat:\n` +
      "  cd C:\\AI\\AI-Mockup-Engine\n" +
      "  .\\.venv\\Scripts\\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8090\n\n" +
      "Sonra tarayıcıda:  http://127.0.0.1:8090\n\n" +
      "Arayüz artık sunucuyla AYNI porttan açılıyor;\n" +
      "ayrı bir statik sunucuya gerek yok."
    );
  }
}

// --------------------------------------------------------------------
// Model
// --------------------------------------------------------------------

function onModelChange() {
  const m = dom.models.value || "";

  if (FLATLAY_RE.test(m)) {
    dom.modelInfo.textContent = "⚠ flatlay modeli — ikinci faz, kalibrasyonu tamamlanmadı";
  } else if (m === "test-model") {
    dom.modelInfo.textContent = "sentetik test modeli — yayınlanabilir çıktı üretmez";
  } else {
    dom.modelInfo.textContent = serverInfo;
  }

  if (m) {
    dom.modelPreview.src = `${API}/models/${m}/preview?w=520`;
    dom.modelPreviewWrap.hidden = false;
  } else {
    dom.modelPreviewWrap.hidden = true;
  }

  updateRenderButton();
  savePrefs();
  loadPlacement();
}

dom.models.addEventListener("change", onModelChange);
dom.color.addEventListener("change", () => { savePrefs(); scheduleAuto(); });

dom.autoRender.addEventListener("change", () => {
  savePrefs();
  if (dom.autoRender.checked) scheduleAuto();
  else markStale();
});
dom.modelPreview.addEventListener("error", () => {
  dom.modelPreviewWrap.hidden = true;
});

// --------------------------------------------------------------------
// Tasarim secimi
// --------------------------------------------------------------------

function acceptFile(f) {
  if (!f) return;
  if (!f.type.startsWith("image/")) {
    showError(`Görsel dosya değil: ${f.type || "bilinmiyor"}`);
    return;
  }

  designFile = f;
  if (designUrl) URL.revokeObjectURL(designUrl);
  designUrl = URL.createObjectURL(f);

  dom.designPreview.src = designUrl;
  dom.designPreview.hidden = false;
  dom.dropText.hidden = true;
  dom.drop.classList.add("has-file");

  // Alfa kanali baski tasarimlarinda sart; JPEG'de alfa YOKTUR ve arka
  // plan opak basilir. Kullaniciyi burada uyariyoruz.
  const kb = (f.size / 1024).toFixed(0);
  const warn = /jpe?g$/i.test(f.type) ? "  ⚠ JPEG: şeffaflık yok" : "";
  dom.designInfo.textContent = `${f.name} · ${kb} KB${warn}`;

  clearError();
  updateRenderButton();
  loadPlacement();
}

dom.drop.addEventListener("click", () => dom.file.click());
dom.file.addEventListener("change", (e) => acceptFile(e.target.files[0]));

["dragenter", "dragover"].forEach((ev) =>
  dom.drop.addEventListener(ev, (e) => {
    e.preventDefault();
    dom.drop.classList.add("is-over");
  })
);
["dragleave", "drop"].forEach((ev) =>
  dom.drop.addEventListener(ev, (e) => {
    e.preventDefault();
    dom.drop.classList.remove("is-over");
  })
);
dom.drop.addEventListener("drop", (e) => acceptFile(e.dataTransfer.files[0]));

// Sayfanin geri kalanina birakilan dosya tarayicida ACILIR ve calisma
// kaybolur. Varsayilan davranisi kapatiyoruz.
["dragover", "drop"].forEach((ev) =>
  window.addEventListener(ev, (e) => {
    if (!dom.drop.contains(e.target)) e.preventDefault();
  })
);

// Panodan yapistirma
window.addEventListener("paste", (e) => {
  const item = [...(e.clipboardData?.items || [])]
    .find((i) => i.type.startsWith("image/"));
  if (!item) return;
  const f = item.getAsFile();
  if (f) {
    acceptFile(new File([f], f.name || "pano.png", { type: f.type }));
  }
});

// --------------------------------------------------------------------
// Kalibrasyon
// --------------------------------------------------------------------

TUNING.forEach(({ id, out, off, fmt }) => {
  const input = el(id);
  const output = el(out);
  input.addEventListener("input", () => {
    const v = parseFloat(input.value);
    const isSet = v > off;
    output.textContent = isSet ? fmt(v) : "meta.json";
    output.classList.toggle("is-set", isSet);
    if (id === "scale") layoutPlacement();
    markStale();
  });
  input.addEventListener("change", () => { savePrefs(); scheduleAuto(); });
});

dom.reset.addEventListener("click", () => {
  flipH = false; flipV = false;
  applyFlipPreview();
  TUNING.forEach(({ id, out, off }) => {
    el(id).value = off;
    el(out).textContent = "meta.json";
    el(out).classList.remove("is-set");
  });
  savePrefs();
  scheduleAuto();
});

// --------------------------------------------------------------------
// Zoom / gorunum
// --------------------------------------------------------------------

function applyZoom() {
  const zoomed = zoom > 0;
  dom.stage.classList.toggle("is-zoomed", zoomed);
  if (zoomed) {
    dom.result.style.width = `${dom.result.naturalWidth * zoom}px`;
    dom.result.style.maxWidth = "none";
    dom.result.style.maxHeight = "none";
    dom.zoomLabel.textContent = `${Math.round(zoom * 100)}%`;
  } else {
    dom.result.style.width = "";
    dom.result.style.maxWidth = "";
    dom.result.style.maxHeight = "";
    dom.zoomLabel.textContent = "fit";
  }
}

function setZoom(z) {
  zoom = Math.max(0, Math.min(z, 4));
  applyZoom();
}

dom.zoomIn.addEventListener("click", () => setZoom(zoom === 0 ? 1 : zoom * 1.5));
dom.zoomOut.addEventListener("click", () => {
  if (zoom === 0) return;
  const next = zoom / 1.5;
  setZoom(next < 0.35 ? 0 : next);
});
dom.zoomFit.addEventListener("click", () => setZoom(0));

// Zoom'da suruklemeyle gezinme
let pan = null;
dom.stage.addEventListener("mousedown", (e) => {
  if (zoom === 0) return;
  pan = { x: e.clientX, y: e.clientY, l: dom.stage.scrollLeft, t: dom.stage.scrollTop };
  dom.stage.classList.add("is-panning");
  e.preventDefault();
});
window.addEventListener("mousemove", (e) => {
  if (!pan) return;
  dom.stage.scrollLeft = pan.l - (e.clientX - pan.x);
  dom.stage.scrollTop = pan.t - (e.clientY - pan.y);
});
window.addEventListener("mouseup", () => {
  pan = null;
  dom.stage.classList.remove("is-panning");
});

function setView(which) {
  view = which;
  dom.viewResult.classList.toggle("is-active", which === "result");
  dom.viewBase.classList.toggle("is-active", which === "base");
  dom.result.src = which === "base"
    ? `${API}/models/${dom.models.value}/preview?w=1600`
    : resultUrl;
}

dom.viewResult.addEventListener("click", () => setView("result"));
dom.viewBase.addEventListener("click", () => setView("base"));

// --------------------------------------------------------------------
// Gecmis
// --------------------------------------------------------------------

function renderHistory() {
  dom.historyWrap.hidden = history.length === 0;
  dom.history.innerHTML = "";

  history.forEach((h, i) => {
    const card = document.createElement("button");
    card.className = "hcard" + (i === 0 ? " is-active" : "");
    card.title = `${h.model}${h.color ? " · " + h.color : ""}`;

    const img = document.createElement("img");
    img.src = h.url;
    img.alt = "";

    const label = document.createElement("span");
    label.textContent = `${h.model.split("/").pop()}${h.color ? " · " + h.color : ""}`;

    card.append(img, label);
    card.addEventListener("click", () => restore(h));
    dom.history.appendChild(card);
  });
}

function restore(h) {
  resultUrl = h.url;
  dom.result.src = h.url;
  dom.result.hidden = false;
  dom.stageEmpty.hidden = true;
  dom.download.href = h.url;
  dom.download.download = h.filename;
  dom.download.hidden = false;
  dom.meta.textContent = h.meta;
  setView("result");

  // Ayarlari da geri yukle -- kalibrasyon karsilastirmasinin asil faydasi.
  if ([...dom.models.options].some((o) => o.value === h.model)) {
    dom.models.value = h.model;
    onModelChange();
  }
  dom.color.value = h.color || "";
  if (h.flip) {
    flipH = h.flip.h; flipV = h.flip.v;
    applyFlipPreview();
  }
  if (h.place) {
    place.x = h.place.x; place.y = h.place.y; place.rot = h.place.rot;
    layoutPlacement();
  }
  TUNING.forEach(({ id, out, off, fmt }) => {
    const v = h.tuning[id];
    el(id).value = v;
    const n = parseFloat(v);
    el(out).textContent = n > off ? fmt(n) : "meta.json";
    el(out).classList.toggle("is-set", n > off);
  });

  [...dom.history.children].forEach((c, i) =>
    c.classList.toggle("is-active", history[i] === h)
  );
}

dom.clearHistory.addEventListener("click", () => {
  // Blob URL'leri serbest birak, yoksa bellekte birikirler.
  history.forEach((h) => { if (h.url !== resultUrl) URL.revokeObjectURL(h.url); });
  history = [];
  renderHistory();
});


// --------------------------------------------------------------------
// Yerlestirme tuvali
// --------------------------------------------------------------------

function quadBox(quad) {
  const xs = quad.map((p) => p[0]);
  const ys = quad.map((p) => p[1]);
  return {
    x: Math.min(...xs), y: Math.min(...ys),
    w: Math.max(...xs) - Math.min(...xs),
    h: Math.max(...ys) - Math.min(...ys),
  };
}

async function loadPlacement() {
  const m = dom.models.value;
  if (!m || !designFile) { dom.placeWrap.hidden = true; return; }

  try {
    const res = await fetch(`${API}/models/${m}/meta`);
    if (!res.ok) throw new Error();
    const info = await res.json();
    if (!info.print_quad || info.print_quad.length !== 4) throw new Error();

    place.quad = info.print_quad;
    place.baseW = info.width;
    place.baseH = info.height;
    place.garmentCx = info.garment_cx ?? null;
  } catch {
    dom.placeWrap.hidden = true;
    return;
  }

  dom.placeBase.src = `${API}/models/${m}/preview?w=560`;
  dom.placeDesignImg.src = designUrl;
  dom.placeWrap.hidden = false;
  layoutPlacement();
}

function layoutPlacement() {
  if (!place.quad || !place.baseW) return;

  const shown = dom.placeCanvas.clientWidth || 520;
  const k = shown / place.baseW;
  dom.placeCanvas.style.height = `${place.baseH * k}px`;

  const box = quadBox(place.quad);
  const qw = box.w * k;
  const qh = box.h * k;

  // Baski alani sinirlari -- sabit
  Object.assign(dom.placeQuad.style, {
    left: `${box.x * k}px`, top: `${box.y * k}px`,
    width: `${qw}px`, height: `${qh}px`,
  });

  // Tasarim: baski alaninin icinde, olcek slider'i kadar buyuk
  const scaleRaw = parseFloat(el("scale").value);
  const s = scaleRaw > 0 ? scaleRaw : 0.95;

  const iw = dom.placeDesignImg.naturalWidth || 1;
  const ih = dom.placeDesignImg.naturalHeight || 1;
  const fit = Math.min(qw / iw, qh / ih) * s;
  const dw = iw * fit;
  const dh = ih * fit;

  // offset baski alani GENISLIGI oraninda -- sunucuyla ayni birim
  const dx = place.x * qw;
  const dy = place.y * qw;

  Object.assign(dom.placeDesign.style, {
    width: `${dw}px`,
    height: `${dh}px`,
    left: `${box.x * k + (qw - dw) / 2 + dx}px`,
    top: `${box.y * k + (qh - dh) / 2 + dy}px`,
    transform: `rotate(${place.rot}deg)`,
  });

  // Merkez kilavuzlari: tasarim yatayda/dikeyde ortaya yakinsa cizgi
  // beliriyor. Goz karariyla ortalamak yerine kesin geri bildirim.
  const SNAP = 0.012;
  const onX = Math.abs(place.x) < SNAP;
  const onY = Math.abs(place.y) < SNAP;

  // Dikey kilavuz GIYSININ ortasindan gecer, baski alaninin degil --
  // baski alani gogus hizasinda ve tisortun tam ortasinda olmayabilir.
  const gx = (place.garmentCx != null ? place.garmentCx * k
                                      : box.x * k + qw / 2);
  dom.guideV.style.left = `${gx}px`;
  dom.guideH.style.top = `${box.y * k + qh / 2}px`;
  dom.guideV.classList.toggle("is-on", onX);
  dom.guideH.classList.toggle("is-on", onY);
  dom.placeDesign.classList.toggle("is-centered", onX && onY);

  dom.roX.textContent = place.x.toFixed(2) + (onX ? " ●" : "");
  dom.roY.textContent = place.y.toFixed(2) + (onY ? " ●" : "");
  dom.roR.textContent = `${place.rot.toFixed(0)}°`;
  dom.roS.textContent = scaleRaw > 0 ? scaleRaw.toFixed(2) : "meta";
  markStale();
}

dom.placeDesignImg.addEventListener("load", layoutPlacement);
dom.placeBase.addEventListener("load", layoutPlacement);
window.addEventListener("resize", layoutPlacement);

// --- surukleme ---
let dragState = null;

dom.placeDesign.addEventListener("mousedown", (e) => {
  if (e.target === dom.placeRot) return;
  const box = quadBox(place.quad);
  const k = (dom.placeCanvas.clientWidth || 520) / place.baseW;
  dragState = { sx: e.clientX, sy: e.clientY, x: place.x, y: place.y,
                qw: box.w * k };
  dom.placeDesign.classList.add("is-drag");
  e.preventDefault();
});

// --- dondurme ---
let rotState = null;

dom.placeRot.addEventListener("mousedown", (e) => {
  const r = dom.placeDesign.getBoundingClientRect();
  rotState = { cx: r.left + r.width / 2, cy: r.top + r.height / 2,
               start: place.rot, a0: null };
  e.preventDefault();
  e.stopPropagation();
});

window.addEventListener("mousemove", (e) => {
  if (dragState) {
    // Sunucu siniri +-6.0. Surukleme SIRASINDA kisitliyoruz, yoksa
    // kullanici tasarimi cok uzaga tasiyip HTTP 400 aliyordu.
    const lim = (v) => Math.max(-OFFSET_LIMIT, Math.min(OFFSET_LIMIT, v));
    place.x = lim(dragState.x + (e.clientX - dragState.sx) / dragState.qw);
    place.y = lim(dragState.y + (e.clientY - dragState.sy) / dragState.qw);
    layoutPlacement();   // markStale iceride
  } else if (rotState) {
    const a = Math.atan2(e.clientY - rotState.cy, e.clientX - rotState.cx);
    if (rotState.a0 === null) rotState.a0 = a;
    let deg = rotState.start + (a - rotState.a0) * 180 / Math.PI;
    // Shift: 15 derecelik adimlara kilitle
    if (e.shiftKey) deg = Math.round(deg / 15) * 15;
    place.rot = Math.max(-180, Math.min(180, deg));
    layoutPlacement();
  }
});

window.addEventListener("mouseup", () => {
  if (dragState) { dragState = null; dom.placeDesign.classList.remove("is-drag"); savePrefs(); scheduleAuto(); }
  if (rotState) { rotState = null; savePrefs(); scheduleAuto(); }
});



// --------------------------------------------------------------------
// Aynalama
// --------------------------------------------------------------------

function applyFlipPreview() {
  // Tuvaldeki tasarim da aynalanmali, yoksa onizleme render'dan sapar.
  dom.placeDesignImg.style.transform =
    `scale(${flipH ? -1 : 1}, ${flipV ? -1 : 1})`;
  dom.designPreview.style.transform =
    `scale(${flipH ? -1 : 1}, ${flipV ? -1 : 1})`;
  el("flipH").classList.toggle("is-on", flipH);
  el("flipV").classList.toggle("is-on", flipV);
}

el("flipH").addEventListener("click", () => {
  flipH = !flipH;
  applyFlipPreview();
  savePrefs();
  scheduleAuto();
});

el("flipV").addEventListener("click", () => {
  flipV = !flipV;
  applyFlipPreview();
  savePrefs();
  scheduleAuto();
});

dom.placeSave.addEventListener("click", async () => {
  const m = dom.models.value;
  if (!m) return;
  if (!confirm(
    `Bu yerleştirme ${m} için meta.json'a KALICI yazılacak.\n\n` +
    `X ${place.x.toFixed(2)}  Y ${place.y.toFixed(2)}  Açı ${place.rot.toFixed(0)}°\n\n` +
    "Devam?"
  )) return;

  const scaleRaw = parseFloat(el("scale").value);
  try {
    const res = await fetch(`${API}/models/${m}/quad`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        offset_x: place.x,
        offset_y: place.y,
        rotate: place.rot,
        design_scale: scaleRaw > 0 ? scaleRaw : null,
      }),
    });
    const j = await res.json();
    if (!res.ok) throw new Error(JSON.stringify(j.detail || j, null, 2));

    // Kaydedildi -> offsetler artik sifir, yeni quad varsayilan oldu.
    place.x = 0; place.y = 0; place.rot = 0;
    await loadPlacement();
    savePrefs();
    showError("Kaydedildi.\n\n" + j.uyari);
  } catch (err) {
    showError(String(err.message || err));
  }
});

dom.placeReset.addEventListener("click", () => {
  place.x = 0; place.y = 0; place.rot = 0;
  layoutPlacement();
  savePrefs();
});

// --- klavye ---
window.addEventListener("keydown", (e) => {
  if (dom.placeWrap.hidden) return;
  const tag = (e.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "select" || tag === "textarea") return;

  const step = e.shiftKey ? 0.05 : 0.01;
  let handled = true;

  switch (e.key) {
    case "ArrowLeft":  place.x -= step; break;
    case "ArrowRight": place.x += step; break;
    case "ArrowUp":    place.y -= step; break;
    case "ArrowDown":  place.y += step; break;
    case "r": place.rot = Math.min(180, place.rot + (e.shiftKey ? 15 : 1)); break;
    case "R": place.rot = Math.max(-180, place.rot - 15); break;
    default: handled = false;
  }

  if (handled) {
    e.preventDefault();
    place.x = Math.max(-OFFSET_LIMIT, Math.min(OFFSET_LIMIT, place.x));
    place.y = Math.max(-OFFSET_LIMIT, Math.min(OFFSET_LIMIT, place.y));
    layoutPlacement();
    savePrefs();
    scheduleAuto();
  }
});



// --------------------------------------------------------------------
// Bayat gostergesi
// --------------------------------------------------------------------

/* Ekrandaki mockup, o anki ayarlarla uretilmis mi? Kullanici tasarimi
 * surukleyip RENDER'a basmadigini fark edemiyordu: tuvalde tasarim
 * hareket ediyor ama alttaki mockup eski kaliyordu. */
let lastRendered = null;

function currentSettings() {
  const tuning = {};
  TUNING.forEach(({ id }) => { tuning[id] = el(id).value; });
  return JSON.stringify({
    model: dom.models.value,
    color: dom.color.value,
    tuning,
    x: +place.x.toFixed(4),
    y: +place.y.toFixed(4),
    rot: +place.rot.toFixed(2),
    fh: flipH, fv: flipV,
    design: designFile ? `${designFile.name}:${designFile.size}` : null,
  });
}

function markStale() {
  const changed = lastRendered !== null && currentSettings() !== lastRendered;
  dom.stale.hidden = !changed;
  dom.placeCanvas.classList.toggle("is-stale", changed);
}

// --------------------------------------------------------------------
// Canli onizleme
// --------------------------------------------------------------------

let autoTimer = null;

/* Kivrim ve golge CSS ile taklit edilemez -- gercek displacement ve
 * shading haritalari gerekiyor. Bu yuzden "canli onizleme" gercek bir
 * render: ayar degisince kisa bir bekleme sonrasi motora gidiyor.
 * Bekleme, slider surukleneken her adimda istek atmayi onluyor. */
function scheduleAuto() {
  markStale();
  if (!dom.autoRender.checked) {
    // Kapaliyken sessiz kalmak yerine ne yapilmasi gerektigini soyle.
    dom.stale.textContent = "Ayarlar değişti — RENDER'a bas (canlı önizleme kapalı)";
    return;
  }
  dom.stale.textContent = "Render ediliyor…";
  if (!designFile || !dom.models.value) return;
  clearTimeout(autoTimer);
  autoTimer = setTimeout(() => doRender({ auto: true }), 450);
}

// --------------------------------------------------------------------
// Render
// --------------------------------------------------------------------

async function doRender(opts = {}) {
  if (!designFile || !dom.models.value) return;

  // Onceki render'i IPTAL ET, sirayi bekletme. Eskiden "devam eden
  // varsa cik" deniyordu ve manuel RENDER, suren canli onizlemeye
  // takilip SESSIZCE iptal oluyordu -- kullanici degisikligin
  // yansimadigini goruyordu.
  if (inflight) inflight.abort();
  const ctl = new AbortController();
  inflight = ctl;

  clearError();
  dom.busy.hidden = false;
  dom.render.disabled = true;

  const body = new FormData();
  body.append("design_file", designFile);
  body.append("model_id", dom.models.value);
  if (dom.color.value) body.append("color", dom.color.value);

  // Dokunulmamis slider gonderilmez -> meta.json degeri gecerli kalir.
  const tuning = {};
  TUNING.forEach(({ id, off }) => {
    const raw = el(id).value;
    tuning[id] = raw;
    const v = parseFloat(raw);
    if (v > off) body.append(id, String(v));
  });

  if (flipH) body.append("flip_h", "true");
  if (flipV) body.append("flip_v", "true");

  if (place.x) body.append("offset_x", place.x.toFixed(4));
  if (place.y) body.append("offset_y", place.y.toFixed(4));
  if (place.rot) body.append("rotate", place.rot.toFixed(2));

  const started = performance.now();

  try {
    const res = await fetch(`${API}/render`, {
      method: "POST", body, signal: ctl.signal,
    });

    if (!res.ok) {
      let detail;
      try {
        const j = await res.json();
        detail = typeof j.detail === "object"
          ? JSON.stringify(j.detail, null, 2)
          : String(j.detail);
      } catch {
        detail = await res.text();
      }
      throw new Error(`HTTP ${res.status}\n${detail}`);
    }

    const blob = await res.blob();
    resultUrl = URL.createObjectURL(blob);

    dom.result.src = resultUrl;
    dom.result.hidden = false;
    dom.stageEmpty.hidden = true;

    const safeModel = dom.models.value.replace(/\//g, "_");
    const suffix = dom.color.value ? `-${dom.color.value}` : "";
    const filename = `${safeModel}${suffix}.png`;
    dom.download.href = resultUrl;
    dom.download.download = filename;
    dom.download.hidden = false;

    const clientMs = Math.round(performance.now() - started);
    const serverMs = res.headers.get("X-Render-Ms");
    const kb = (blob.size / 1024).toFixed(0);

    // Sunucunun GERCEKTEN aldigi ayarlar. Bos ise parametreler
    // sunucuya ULASMIYOR demektir -- tahmin etmeye gerek kalmiyor.
    const appliedRaw = res.headers.get("X-Applied");
    let appliedText = "";
    if (appliedRaw) {
      try {
        const ap = JSON.parse(appliedRaw);
        const keys = Object.keys(ap);
        appliedText = keys.length
          ? ` · sunucu: ${keys.map((k) => `${k}=${ap[k]}`).join(" ")}`
          : " · sunucu: AYAR YOK";
      } catch { /* yoksay */ }
    } else {
      appliedText = " · X-Applied yok (sunucu eski)";
    }

    lastRendered = currentSettings();
    dom.stale.hidden = true;
    dom.placeCanvas.classList.remove("is-stale");

    const metaText =
      `${dom.models.value}${suffix} · ${kb} KB · ` +
      `${serverMs ? `render ${serverMs} ms · ` : ""}toplam ${clientMs} ms` +
      appliedText;
    dom.meta.textContent = metaText;

    if (!opts.auto) history.unshift({
      url: resultUrl,
      model: dom.models.value,
      color: dom.color.value,
      tuning: { ...tuning },
      place: { x: place.x, y: place.y, rot: place.rot },
      flip: { h: flipH, v: flipV },
      filename,
      meta: metaText,
    });
    if (history.length > HISTORY_MAX) {
      URL.revokeObjectURL(history.pop().url);
    }
    if (!opts.auto) renderHistory();

    [dom.viewResult, dom.viewBase, dom.zoomIn, dom.zoomOut, dom.zoomFit]
      .forEach((b) => { b.disabled = false; });
    setView("result");
    setZoom(0);
    savePrefs();
  } catch (err) {
    // Iptal edilen istek hata degil -- yenisi calisiyor.
    if (err.name === "AbortError") return;
    // "Failed to fetch" tarayicinin genel ag hatasi ve sebebi
    // gostermez. En yaygin nedenleri burada aciyoruz.
    const msg = String(err.message || err);
    if (/failed to fetch|networkerror|load failed/i.test(msg)) {
      showError(
        "İstek sunucuya ulaşamadı.\n\n" +
        "GET istekleri çalışıp POST çalışmıyorsa en olası neden\n" +
        "python-multipart paketinin eksik olması.\n\n" +
        "Teşhis için:\n" +
        "  cd C:\\AI\\AI-Mockup-Engine\\web\n" +
        "  .\\teshis.ps1\n\n" +
        "Ayrıca kontrol et:\n" +
        "  · uvicorn penceresinde traceback var mı\n" +
        "  · F12 → Network → render → Status\n" +
        "  · sayfa file:// yerine http:// ile açık mı"
      );
    } else {
      showError(msg);
    }
  } finally {
    if (inflight === ctl) {
      inflight = null;
      dom.busy.hidden = true;
      updateRenderButton();
    }
  }
}

dom.render.addEventListener("click", () => doRender());

window.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    doRender();
  }
});

connect();
