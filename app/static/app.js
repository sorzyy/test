(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const els = {
    form: $("form"), url: $("url"), go: $("go"), clear: $("clear"), paste: $("paste"),
    settingsBtn: $("settings-btn"), settings: $("settings"),
    status: $("status"), statusText: $("status-text"), statusMeta: $("status-meta"), bar: $("bar-fill"),
    error: $("error"), errorText: $("error-text"), errorDetails: $("error-details"), errorDetail: $("error-detail"),
    picker: $("picker"), pickerTitle: $("picker-title"), pickerSub: $("picker-sub"), grid: $("grid"),
    dlAll: $("dl-all"), dlAudio: $("dl-audio"), engine: $("engine"), keyField: $("key-field"),
  };

  // --- réglages persistants -------------------------------------------------
  const DEFAULTS = {
    mode: "auto", quality: "1080", codec: "h264", audio_format: "mp3", audio_bitrate: "320",
    convert_gif: true, auto_start: true, api_key: "",
  };
  const store = {
    get() {
      try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem("saphir") || "{}") }; }
      catch { return { ...DEFAULTS }; }
    },
    set(patch) {
      const next = { ...store.get(), ...patch };
      try { localStorage.setItem("saphir", JSON.stringify(next)); } catch { /* navigation privée */ }
      return next;
    },
  };
  let prefs = store.get();

  const fields = ["quality", "codec", "audio_format", "audio_bitrate", "convert_gif", "auto_start", "api_key"];
  for (const name of fields) {
    const el = $(name);
    if (el.type === "checkbox") el.checked = !!prefs[name]; else el.value = prefs[name];
    el.addEventListener("change", () => {
      prefs = store.set({ [name]: el.type === "checkbox" ? el.checked : el.value });
    });
  }

  const modeButtons = document.querySelectorAll("[data-mode]");
  const renderMode = () => modeButtons.forEach((b) => b.setAttribute("aria-checked", String(b.dataset.mode === prefs.mode)));
  modeButtons.forEach((b) => b.addEventListener("click", () => { prefs = store.set({ mode: b.dataset.mode }); renderMode(); }));
  renderMode();

  els.settingsBtn.addEventListener("click", () => {
    const open = els.settings.hidden;
    els.settings.hidden = !open;
    els.settingsBtn.setAttribute("aria-expanded", String(open));
  });

  const options = () => ({
    mode: prefs.mode, quality: prefs.quality, codec: prefs.codec,
    audio_format: prefs.audio_format, audio_bitrate: prefs.audio_bitrate, convert_gif: !!prefs.convert_gif,
  });

  // --- API -------------------------------------------------------------------
  // vide = même serveur ; sur GitHub Pages, config.js pointe vers le serveur saphir
  const API = String((window.SAPHIR_CONFIG || {}).api || "").replace(/\/+$/, "");
  const apiUrl = (path) => (/^https?:/.test(path) ? path : API + path);

  async function api(path, body) {
    const headers = { "Accept": "application/json" };
    if (body) headers["Content-Type"] = "application/json";
    if (prefs.api_key) headers["Authorization"] = "Api-Key " + prefs.api_key;
    let res;
    try {
      res = await fetch(apiUrl(path), { method: body ? "POST" : "GET", headers, body: body ? JSON.stringify(body) : undefined });
    } catch {
      throw { message: API
        ? "Impossible de joindre le serveur saphir. S'il était en veille, il redémarre : réessaie dans 30 secondes."
        : "Impossible de joindre le serveur. Vérifie ta connexion." };
    }
    let data = null;
    try { data = await res.json(); } catch { /* réponse vide */ }
    if (!res.ok) throw (data && data.error) || { message: `Erreur serveur (${res.status}).` };
    return data;
  }

  // --- affichage ---------------------------------------------------------------
  const fmtBytes = (n) => {
    if (!n) return "";
    const u = ["o", "Ko", "Mo", "Go"]; let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(n < 10 && i ? 1 : 0)} ${u[i]}`;
  };
  const fmtDur = (s) => {
    if (!s) return "";
    s = Math.round(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return (h ? `${h}:${String(m).padStart(2, "0")}` : `${m}`) + `:${String(sec).padStart(2, "0")}`;
  };

  function showStatus(text, meta = "", progress = null) {
    els.status.hidden = false;
    els.statusText.textContent = text;
    els.statusMeta.textContent = meta;
    if (progress === null) {
      els.bar.classList.add("indeterminate");
      els.bar.style.width = "";
    } else {
      els.bar.classList.remove("indeterminate");
      els.bar.style.width = `${Math.max(2, Math.min(100, progress))}%`;
    }
  }
  const hideStatus = () => { els.status.hidden = true; };

  function showError(err) {
    hideStatus();
    els.error.hidden = false;
    els.errorText.textContent = (err && err.message) || "Une erreur est survenue.";
    const detail = err && err.detail;
    els.errorDetails.hidden = !detail;
    els.errorDetail.textContent = detail || "";
  }
  const hideError = () => { els.error.hidden = true; };

  const busy = (on) => { els.go.disabled = on; };

  // --- flux principal ----------------------------------------------------------
  let current = null; // résultat d'analyse en cours
  let running = false;

  async function start() {
    const url = els.url.value.trim();
    if (!url || running) return;
    running = true;
    busy(true);
    hideError();
    els.picker.hidden = true;
    showStatus(API ? "analyse du lien… (le 1er essai peut prendre ~30 s si le serveur dormait)" : "analyse du lien…");
    try {
      current = await api("/api/resolve", { url });
      const items = current.items;
      const audioOnlySlideshow = prefs.mode === "audio" && current.audio && items.every((i) => i.type === "photo");
      if (audioOnlySlideshow) {
        await download("audio");
      } else if (items.length === 1) {
        await download(0);
      } else {
        hideStatus();
        renderPicker(current);
      }
    } catch (err) {
      showError(err);
    } finally {
      running = false;
      busy(false);
    }
  }

  async function download(index, tile) {
    const label = index === "all" ? "préparation de l'archive…" : "téléchargement…";
    showStatus(label, "", 0);
    if (tile) tile.classList.add("busy");
    try {
      let job = await api("/api/jobs", { token: current.token, index, options: options() });
      while (job.status !== "done" && job.status !== "error") {
        await new Promise((r) => setTimeout(r, 450));
        job = await api(`/api/jobs/${job.id}`);
        const phase = job.status === "processing" ? "conversion…" : (job.phase ? `téléchargement ${job.phase}…` : "téléchargement…");
        const meta = [job.speed ? `${fmtBytes(job.speed)}/s` : "", job.progress != null ? `${Math.round(job.progress)}%` : ""]
          .filter(Boolean).join(" · ");
        showStatus(phase, meta, job.status === "processing" ? null : job.progress);
      }
      if (job.status === "error") throw job.error;
      showStatus(`✓ ${job.filename}`, fmtBytes(job.size), 100);
      save(apiUrl(job.url), job.filename);
      if (tile) tile.classList.add("done");
    } catch (err) {
      showError(err);
    } finally {
      if (tile) tile.classList.remove("busy");
    }
  }

  function save(url, filename) {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || "";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  const TYPE_LABEL = { photo: "photo", video: "vidéo", gif: "gif", audio: "audio" };

  function renderPicker(res) {
    els.grid.textContent = "";
    els.pickerTitle.textContent = res.title || "plusieurs médias trouvés";
    const counts = res.items.reduce((acc, i) => ((acc[i.type] = (acc[i.type] || 0) + 1), acc), {});
    els.pickerSub.textContent = [res.author ? `@${res.author}` : "", Object.entries(counts)
      .map(([t, n]) => `${n} ${TYPE_LABEL[t] || t}${n > 1 ? "s" : ""}`).join(", ")].filter(Boolean).join(" · ");
    els.dlAudio.hidden = !res.audio;
    const tpl = $("card-tpl");
    res.items.forEach((item, i) => {
      const node = tpl.content.firstElementChild.cloneNode(true);
      const img = node.querySelector("img");
      if (item.hasThumbnail) img.src = apiUrl(`/api/thumb/${res.token}/${i}`); else img.remove();
      img.onerror = () => img.remove();
      node.querySelector(".badge").textContent = TYPE_LABEL[item.type] || item.type;
      node.querySelector(".dur").textContent = fmtDur(item.duration);
      node.querySelector(".tile-name").textContent = `${i + 1}. ${item.width && item.height ? `${item.width}×${item.height}` : TYPE_LABEL[item.type]}`;
      node.addEventListener("click", () => download(i, node));
      els.grid.appendChild(node);
    });
    els.picker.hidden = false;
  }

  els.dlAll.addEventListener("click", () => current && download("all"));
  els.dlAudio.addEventListener("click", () => current && download("audio"));

  els.form.addEventListener("submit", (e) => { e.preventDefault(); start(); });

  const looksLikeUrl = (v) => /^(https?:\/\/)?[\w-]+(\.[\w-]+)+\/\S*/i.test(v.trim()) || /https?:\/\//.test(v);
  const syncClear = () => { els.clear.hidden = !els.url.value; };
  els.url.addEventListener("input", syncClear);
  els.url.addEventListener("paste", () => setTimeout(() => {
    syncClear();
    if (prefs.auto_start && looksLikeUrl(els.url.value)) start();
  }, 0));
  els.clear.addEventListener("click", () => { els.url.value = ""; syncClear(); els.url.focus(); });

  els.paste.addEventListener("click", async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        els.url.value = text.trim();
        syncClear();
        if (prefs.auto_start && looksLikeUrl(text)) start();
      }
    } catch {
      els.url.focus();
      showError({ message: "Ton navigateur bloque l'accès au presse-papiers : colle le lien à la main (Ctrl+V / appui long)." });
    }
  });

  // --- infos serveur ---------------------------------------------------------
  const ago = (ts) => {
    if (!ts) return "";
    const m = Math.round((Date.now() / 1000 - ts) / 60);
    if (m < 1) return "à l'instant";
    if (m < 60) return `il y a ${m} min`;
    const h = Math.round(m / 60);
    return h < 48 ? `il y a ${h} h` : `il y a ${Math.round(h / 24)} j`;
  };
  if ((window.SAPHIR_CONFIG || {}).missing) {
    showError({ message: "Le serveur saphir n'est pas encore branché sur cette page. Voir le README (déploiement)." });
  }
  api("/api/status").then((s) => {
    els.keyField.hidden = !s.auth_required;
    if (s.auth_required && !prefs.api_key) els.settings.hidden = false;
    const v = s.versions || {};
    const parts = [`saphir ${s.version}`, v["yt-dlp"] && `yt-dlp ${v["yt-dlp"]}`, v["gallery-dl"] && `gallery-dl ${v["gallery-dl"]}`];
    if (s.update && s.update.auto) parts.push(s.update.last_check ? `maj auto ${ago(s.update.last_check)}` : "maj auto activée");
    els.engine.textContent = parts.filter(Boolean).join(" · ");
  }).catch(() => {});

  // --- lien reçu via ?u= (partage depuis une appli mobile / favori) -----------
  const params = new URLSearchParams(location.search);
  const shared = params.get("u") || params.get("url") || params.get("text");
  if (shared) {
    els.url.value = shared;
    syncClear();
    history.replaceState(null, "", "/");
    start();
  }
})();
