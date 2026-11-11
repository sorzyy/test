"use strict";

/* ---------- Petits utilitaires ---------- */

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem("laoshi." + key); return v === null ? fallback : JSON.parse(v); }
    catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem("laoshi." + key, JSON.stringify(value)); } catch { /* stockage indisponible */ }
  },
};

const settings = Object.assign(
  { level: "debutant", maxNew: 2, rate: 0.8, server: "", token: "" },
  store.get("settings", {})
);
const saveSettings = () => store.set("settings", settings);

function setStatus(text, isError = false) {
  const el = $("#status");
  el.textContent = text;
  el.classList.toggle("error", isError);
}

/* ---------- Pinyin coloré par ton ---------- */

const TONE_MARKS = { "̄": 1, "́": 2, "̌": 3, "̀": 4 };
function toneOf(syllable) {
  for (const ch of syllable.normalize("NFD")) if (TONE_MARKS[ch]) return TONE_MARKS[ch];
  return 5;
}
function pinyinHTML(pinyin) {
  return String(pinyin || "")
    .split(/(\s+)/)
    .map((part) => (/^\s+$/.test(part) || !part ? part : `<span class="t${toneOf(part)}">${esc(part)}</span>`))
    .join("");
}

/* ---------- Voix (synthèse vocale du navigateur) ---------- */

const synth = window.speechSynthesis;
let voices = [];
function loadVoices() {
  voices = synth ? synth.getVoices() : [];
  const zh = pickVoice("zh-CN");
  $("#voice-info").textContent = !synth
    ? "Synthèse vocale indisponible sur ce navigateur."
    : zh ? `Voix chinoise : ${zh.name}` : "Aucune voix chinoise installée : ajoute « Chinois (Chine) » dans les réglages de synthèse vocale du téléphone.";
}
function pickVoice(lang) {
  const base = lang.slice(0, 2);
  return voices.find((v) => v.lang === lang) || voices.find((v) => v.lang.replace("_", "-").startsWith(base)) || null;
}
if (synth) { loadVoices(); synth.onvoiceschanged = loadVoices; }

let speakQueueId = 0;
function speak(segments) {
  if (!synth) return Promise.resolve();
  synth.cancel();
  const id = ++speakQueueId;
  return segments.reduce((p, seg) => p.then(() => new Promise((resolve) => {
    if (id !== speakQueueId) return resolve();
    const u = new SpeechSynthesisUtterance(seg.text);
    u.lang = seg.lang;
    const v = pickVoice(seg.lang);
    if (v) u.voice = v;
    u.rate = seg.lang === "zh-CN" ? settings.rate : 1;
    u.onend = u.onerror = () => setTimeout(resolve, seg.lang === "zh-CN" ? 450 : 250);
    synth.speak(u);
  })), Promise.resolve());
}
const say = (text, lang = "zh-CN") => speak([{ lang, text }]);

/* ---------- Vocabulaire + répétition espacée (boîtes de Leitner) ---------- */

const DAY = 86400000;
const INTERVALS = [0, 1, 3, 7, 16, 35, 80]; // en jours, par boîte
const KNOWN_BOX = 4;
let deck = store.get("deck", {});
const saveDeck = () => { store.set("deck", deck); updateBadge(); };

function addOrTouch(word) {
  const now = Date.now();
  const card = deck[word.hanzi];
  if (!card) {
    deck[word.hanzi] = {
      hanzi: word.hanzi, pinyin: word.pinyin, fr: word.fr, measure: word.measure, example: word.example,
      tip: word.tip, box: 0, due: now, seen: 1, added: now,
    };
  } else {
    card.seen = (card.seen || 0) + 1;
    card.lastSeen = now;
  }
}
function grade(hanzi, good) {
  const card = deck[hanzi];
  if (!card) return;
  if (good) {
    card.box = Math.min(card.box + 1, INTERVALS.length - 1);
    card.due = Date.now() + INTERVALS[card.box] * DAY;
  } else {
    card.box = 0;
    card.due = Date.now() + 10 * 60000; // revient dans 10 minutes
  }
  saveDeck();
}
const cards = () => Object.values(deck);
const dueCards = () => cards().filter((c) => c.due <= Date.now()).sort((a, b) => a.due - b.due);
const knownList = () => cards().filter((c) => c.box >= KNOWN_BOX).map((c) => c.hanzi);
const learningList = () => cards().filter((c) => c.box < KNOWN_BOX).map((c) => c.hanzi);

function updateBadge() {
  const n = dueCards().length;
  const b = $("#due-badge");
  b.hidden = n === 0;
  b.textContent = n > 99 ? "99+" : n;
  const total = cards().length;
  $("#deck-stats").textContent = `${total} mot${total > 1 ? "s" : ""} · ${knownList().length} maîtrisé${knownList().length > 1 ? "s" : ""} · ${n} à réviser`;
}

/* ---------- Caméra ---------- */

let stream = null;
async function startCamera() {
  if (stream) return attachStream();
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 960 } },
      audio: false,
    });
    attachStream();
  } catch (err) {
    console.warn(err);
    $("#camera-off").hidden = false;
    setStatus("Caméra refusée ou indisponible (il faut HTTPS).", true);
  }
}
function attachStream() {
  for (const v of [$("#video"), $("#video2")]) if (v.srcObject !== stream) v.srcObject = stream;
}
function grabFrame(video) {
  if (!video.videoWidth) return null;
  const max = 1024;
  const scale = Math.min(1, max / Math.max(video.videoWidth, video.videoHeight));
  const c = $("#canvas");
  c.width = Math.round(video.videoWidth * scale);
  c.height = Math.round(video.videoHeight * scale);
  c.getContext("2d").drawImage(video, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.82);
}
function fileToDataURL(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const max = 1024;
      const scale = Math.min(1, max / Math.max(img.width, img.height));
      const c = $("#canvas");
      c.width = Math.round(img.width * scale);
      c.height = Math.round(img.height * scale);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(img.src);
      resolve(c.toDataURL("image/jpeg", 0.82));
    };
    img.onerror = reject;
    img.src = URL.createObjectURL(file);
  });
}

/* ---------- Appel au serveur ---------- */

async function callScan(image, challenge = null) {
  const base = (settings.server || "").replace(/\/+$/, "");
  const headers = { "Content-Type": "application/json" };
  if (settings.token) headers["X-Laoshi-Token"] = settings.token;
  const res = await fetch(`${base}/api/scan`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      image,
      level: settings.level,
      max_new: Number(settings.maxNew),
      known: knownList().slice(-300),
      learning: learningList().slice(-300),
      challenge,
    }),
  });
  if (!res.ok) {
    let msg = `Erreur ${res.status}`;
    try { msg = (await res.json()).detail || msg; } catch { /* pas du JSON */ }
    throw new Error(msg);
  }
  return res.json();
}

/* ---------- Affichage d'une leçon ---------- */

const STATUS_LABEL = { new: "nouveau", review: "à revoir", known: "connu" };

function wordHTML(w, i) {
  const warn = w.pinyin_check && !w.pinyin_check.ok
    ? `<div class="warn">⚠ Pinyin à vérifier — dictionnaire : ${pinyinHTML(w.pinyin_check.dictionary)} (${esc(w.pinyin_check.reason)})</div>` : "";
  return `
    <article class="card word">
      <div class="word-head">
        <span class="hanzi" lang="zh-CN">${esc(w.hanzi)}</span>
        <span class="pinyin">${pinyinHTML(w.pinyin)}</span>
        <button class="speak" data-say="${i}" aria-label="Écouter ${esc(w.hanzi)}">🔊</button>
      </div>
      <div><span class="fr">${esc(w.fr)}</span> <span class="tag ${esc(w.status)}">${STATUS_LABEL[w.status] || ""}</span> <span class="muted">· ${esc(w.where)} · HSK ${w.hsk === 7 ? "—" : esc(w.hsk)}</span></div>
      ${warn}
      <div class="sub"><span class="zh" lang="zh-CN">${esc(w.measure.zh)}</span> · ${pinyinHTML(w.measure.pinyin)} · <span class="muted">${esc(w.measure.fr)}</span></div>
      <div class="sub"><span class="zh" lang="zh-CN">${esc(w.example.zh)}</span><br>${pinyinHTML(w.example.pinyin)}<br><span class="muted">${esc(w.example.fr)}</span></div>
      <div class="tip">💡 ${esc(w.tip)}</div>
    </article>`;
}

function renderLesson(target, data) {
  const words = data.words || [];
  target.innerHTML = `
    ${data.demo ? `<p class="warn">Mode démo : le serveur n'a pas de clé API, la leçon est fictive.</p>` : ""}
    <p class="scene">${esc(data.scene)}</p>
    ${words.length ? words.map(wordHTML).join("") : `<div class="card empty">Je ne vois pas d'objet à t'apprendre ici. Vise un objet de plus près.</div>`}
    <article class="card teacher">
      <div class="muted">Le prof te demande :</div>
      <div class="zh" lang="zh-CN">${esc(data.teacher.zh)}</div>
      <div>${pinyinHTML(data.teacher.pinyin)}</div>
      <div class="muted">${esc(data.teacher.fr)}</div>
      <div class="row" style="margin-top:10px"><button class="btn secondary" data-replay>🔊 Réécouter la leçon</button></div>
    </article>`;
  target.querySelectorAll("[data-say]").forEach((b) => b.addEventListener("click", () => {
    const w = words[Number(b.dataset.say)];
    speak([{ lang: "zh-CN", text: w.hanzi }, { lang: "zh-CN", text: w.example.zh }]);
  }));
  target.querySelector("[data-replay]").addEventListener("click", () => speak(data.speech));
}

/* ---------- Onglet « Voir » ---------- */

let busy = false;
async function runScan(imagePromise) {
  if (busy) return;
  busy = true;
  $("#btn-scan").disabled = true;
  $(".camera").classList.add("busy");
  setStatus("Le prof regarde…");
  try {
    const image = await imagePromise;
    if (!image) throw new Error("Pas encore d'image de la caméra.");
    const data = await callScan(image);
    for (const w of data.words) if (w.status !== "known") addOrTouch(w);
    saveDeck();
    renderLesson($("#result"), data);
    setStatus(data.words.length ? `${data.words.length} mot(s)` : "Rien de nouveau");
    speak(data.speech);
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    busy = false;
    $("#btn-scan").disabled = false;
    $(".camera").classList.remove("busy");
  }
}
$("#btn-scan").addEventListener("click", () => runScan(Promise.resolve(grabFrame($("#video")))));
$("#file").addEventListener("change", (e) => {
  const f = e.target.files[0];
  if (f) runScan(fileToDataURL(f));
  e.target.value = "";
});

let autoTimer = null;
$("#auto").addEventListener("change", (e) => {
  clearInterval(autoTimer);
  autoTimer = null;
  if (e.target.checked) {
    // On attend que le prof ait fini de parler avant la photo suivante.
    autoTimer = setInterval(() => {
      if (!busy && !(synth && synth.speaking) && currentView === "scan" && !document.hidden) {
        runScan(Promise.resolve(grabFrame($("#video"))));
      }
    }, 15000);
  }
});

/* ---------- Onglet « Défi » ---------- */

let challengeCard = null;
function pickChallenge() {
  const due = dueCards();
  const pool = due.length ? due.slice(0, 5) : cards().filter((c) => c.box < KNOWN_BOX);
  const list = pool.length ? pool : cards();
  if (!list.length) return null;
  let next = list[Math.floor(Math.random() * list.length)];
  if (list.length > 1 && challengeCard && next.hanzi === challengeCard.hanzi) {
    next = list.find((c) => c.hanzi !== challengeCard.hanzi);
  }
  return next;
}
function renderChallenge() {
  challengeCard = pickChallenge();
  $("#challenge-result").innerHTML = "";
  const box = $("#challenge-box");
  $("#btn-found").disabled = !challengeCard;
  if (!challengeCard) {
    box.innerHTML = `<p class="empty">Scanne d'abord ton environnement dans l'onglet « Voir » pour récolter des mots.</p>`;
    return;
  }
  box.innerHTML = `
    <div class="muted">Trouve autour de toi :</div>
    <div class="hanzi" lang="zh-CN">${esc(challengeCard.hanzi)}</div>
    <div class="pinyin">${pinyinHTML(challengeCard.pinyin)}</div>
    <details><summary class="muted">Indice</summary><div class="fr">${esc(challengeCard.fr)}</div></details>`;
  say(challengeCard.hanzi);
}
$("#btn-skip").addEventListener("click", renderChallenge);
$("#btn-found").addEventListener("click", async () => {
  if (busy || !challengeCard) return;
  busy = true;
  $("#btn-found").disabled = true;
  setStatus("Le prof vérifie…");
  try {
    const image = grabFrame($("#video2"));
    if (!image) throw new Error("Pas encore d'image de la caméra.");
    const data = await callScan(image, challengeCard.hanzi);
    const ok = data.challenge && data.challenge.found;
    if (ok) grade(challengeCard.hanzi, true);
    $("#challenge-result").innerHTML = `
      <div class="card"><div class="${ok ? "ok" : "ko"}">${ok ? "✓ Trouvé !" : "Pas encore…"}</div>
      <div>${esc(data.challenge ? data.challenge.feedback : "")}</div></div>
      ${ok ? `<button class="btn primary big" id="btn-next" style="width:100%">Mot suivant</button>` : ""}`;
    if (ok) $("#btn-next").addEventListener("click", renderChallenge);
    speak(data.challenge ? [{ lang: "fr-FR", text: data.challenge.feedback }] : []);
    setStatus(ok ? "Défi réussi" : "Cherche encore");
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    busy = false;
    $("#btn-found").disabled = false;
  }
});

/* ---------- Onglet « Révision » ---------- */

function renderReview() {
  const box = $("#review-box");
  const due = dueCards();
  if (!due.length) {
    const total = cards().length;
    box.innerHTML = `<div class="card empty">${total ? "Rien à réviser pour l'instant. Reviens plus tard, ou va scanner de nouveaux objets !" : "Ton vocabulaire est vide. Scanne ce qui t'entoure dans l'onglet « Voir »."}</div>`;
    return;
  }
  const c = due[0];
  box.innerHTML = `
    <p class="muted">${due.length} carte${due.length > 1 ? "s" : ""} à réviser</p>
    <div class="card flash">
      <div class="hanzi" lang="zh-CN">${esc(c.hanzi)}</div>
      <button class="speak" style="margin:8px auto 0" id="rv-say" aria-label="Écouter">🔊</button>
      <div class="answer" id="rv-answer" hidden>
        <div class="pinyin">${pinyinHTML(c.pinyin)}</div>
        <div class="fr">${esc(c.fr)}</div>
        ${c.measure ? `<div class="sub"><span class="zh" lang="zh-CN">${esc(c.measure.zh)}</span> · ${pinyinHTML(c.measure.pinyin)}</div>` : ""}
        ${c.example ? `<div class="sub"><span class="zh" lang="zh-CN">${esc(c.example.zh)}</span><br><span class="muted">${esc(c.example.fr)}</span></div>` : ""}
        ${c.tip ? `<div class="tip">💡 ${esc(c.tip)}</div>` : ""}
      </div>
      <div class="row" id="rv-show-row"><button class="btn primary" id="rv-show">Voir la réponse</button></div>
      <div class="row" id="rv-grade" hidden>
        <button class="btn secondary" id="rv-bad">À revoir</button>
        <button class="btn primary" id="rv-good">Je savais</button>
      </div>
    </div>`;
  $("#rv-say").addEventListener("click", () => say(c.hanzi));
  $("#rv-show").addEventListener("click", () => {
    $("#rv-answer").hidden = false;
    $("#rv-show-row").hidden = true;
    $("#rv-grade").hidden = false;
    speak([{ lang: "zh-CN", text: c.hanzi }, ...(c.example ? [{ lang: "zh-CN", text: c.example.zh }] : [])]);
  });
  $("#rv-bad").addEventListener("click", () => { grade(c.hanzi, false); renderReview(); });
  $("#rv-good").addEventListener("click", () => { grade(c.hanzi, true); renderReview(); });
}

/* ---------- Onglet « Réglages » ---------- */

function initSettings() {
  $("#level").value = settings.level;
  $("#max-new").value = String(settings.maxNew);
  $("#rate").value = String(settings.rate);
  $("#server").value = settings.server;
  $("#token").value = settings.token;
  const bind = (sel, key, conv = (v) => v) => $(sel).addEventListener("change", (e) => { settings[key] = conv(e.target.value.trim()); saveSettings(); checkServer(); });
  bind("#level", "level");
  bind("#max-new", "maxNew", Number);
  bind("#rate", "rate", Number);
  bind("#server", "server");
  bind("#token", "token");
  $("#btn-voice").addEventListener("click", () => speak([{ lang: "zh-CN", text: "你好！我是你的中文老师。" }, { lang: "fr-FR", text: "Bonjour ! Je suis ton prof de chinois." }]));
  $("#btn-export").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify(deck, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `laoshi-vocabulaire-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  });
  $("#import").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try {
      const data = JSON.parse(await f.text());
      for (const [k, v] of Object.entries(data)) if (v && v.hanzi === k) deck[k] = v;
      saveDeck();
      setStatus("Vocabulaire importé");
    } catch { setStatus("Fichier invalide", true); }
    e.target.value = "";
  });
  $("#btn-reset").addEventListener("click", () => {
    if (confirm("Effacer tout ton vocabulaire et ta progression ?")) { deck = {}; saveDeck(); }
  });
}

async function checkServer() {
  try {
    const base = (settings.server || "").replace(/\/+$/, "");
    const h = await (await fetch(`${base}/api/health`)).json();
    if (h.token_required && !settings.token) setStatus("Le serveur demande un jeton (Réglages).", true);
    else setStatus(h.demo ? "Serveur en mode démo" : "Prêt");
  } catch {
    setStatus("Serveur injoignable", true);
  }
}

/* ---------- Navigation ---------- */

let currentView = "scan";
function show(view) {
  currentView = view;
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  if (synth) synth.cancel();
  if (view === "scan" || view === "challenge") startCamera();
  if (view === "challenge") renderChallenge();
  if (view === "review") renderReview();
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));

initSettings();
updateBadge();
checkServer();
startCamera();
