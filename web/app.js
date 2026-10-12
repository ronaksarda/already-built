/* Already Built? front end. No framework: one page, plain DOM. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  // The dragon from fx.js; a silent stand-in when it's missing.
  const buddy = () => window.buddy || { say() {}, listening() {}, quip() {}, off: true };
  const MAX_CHARS = 1200;
  const MAX_IMAGE = 5 * 1024 * 1024;
  const MAX_REC_MS = 120000;
  const POLL_MS = 700;
  const POLL_MAX_S = 300;
  const HISTORY_KEY = "already-built:history:v1";
  const SPEAK_KEY = "already-built:autospeak";
  const THEME_KEY = "already-built:theme";
  const LANG_KEY = "already-built:stt-lang";

  const state = { health: null, jobId: "", runToken: 0, result: null, chat: [], busy: false, chatBusy: false, image: null, historyId: "" };
  const HISTORY_MAX = 40;
  const SIDE_KEY = "already-built:sidebar";

  // ---------- helpers ----------
  function el(tag, attrs = {}, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return n;
  }
  const SVG_NS = "http://www.w3.org/2000/svg";
  function svg(tag, attrs = {}, ...kids) {
    const n = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null) continue;
      if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid) n.append(kid);
    return n;
  }
  // replaceChildren() turns null into the text "null", so drop empty slots first.
  const fill = (node, ...kids) => node.replaceChildren(...kids.flat(Infinity).filter((k) => k != null && k !== false && k !== ""));
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
  const num = (v, d = 0) => (typeof v === "number" && isFinite(v) ? v : d);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const reduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch { return false; } },
    del(k) { try { localStorage.removeItem(k); } catch { /* storage blocked */ } },
  };
  async function api(path, opts = {}) {
    let r;
    try { r = await fetch(path, opts); }
    catch { const e = new Error("Can't reach the server. Check your connection, or that the server is still running."); e.network = true; throw e; }
    let body = null;
    try { body = await r.json(); } catch { /* non-JSON error page */ }
    if (!r.ok) {
      let msg = body && body.detail;
      if (Array.isArray(msg)) msg = "That input was rejected. Shorten it and try again."; // FastAPI validation list
      const e = new Error(msg || `Request failed (HTTP ${r.status}).`);
      e.status = r.status;
      throw e;
    }
    if (!body) throw new Error("The server sent an empty answer. Try again.");
    return body;
  }
  function hint(msg, bad = false) { const h = $("hint"); h.textContent = msg || ""; h.classList.toggle("bad", !!bad && !!msg); }
  const fmtDate = (ms) => { const d = new Date(ms); return isNaN(d) ? "" : d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" }); };

  // ---------- health ----------
  async function loadHealth() {
    try {
      state.health = await api("/api/health");
      renderHistory();
      const h = state.health;
      const parts = [];
      if (!h.gemma) parts.push("Search planner offline");
      if (!h.groq) parts.push("Advisor offline");
      if (h.embed_error) parts.push("Similarity model missing");
      $("status").textContent = parts.join(" · ");
      $("status").title = [h.embed_error, !h.gemma && "No GEMINI_API_KEY: plain keyword search is used.", !h.groq && "No GROQ_API_KEY: rule-based report, no chat."].filter(Boolean).join(" ");
      $("status").classList.toggle("warn", parts.length > 0);
      applyChatAvailability();
    } catch (e) {
      $("status").textContent = "Server unreachable";
      $("status").classList.add("warn");
    }
  }
  const chatOn = () => !state.health || state.health.groq;
  function applyChatAvailability() {
    const on = chatOn();
    $("chatSend").disabled = !on || state.chatBusy;
    $("chatInput").disabled = !on;
    $("chatMic").disabled = !on;
    $("chatInput").placeholder = on ? "Ask about a niche, MVP scope, or a gap…" : "The advisor needs GROQ_API_KEY on the server.";
    $("suggest").querySelectorAll("button").forEach((b) => { b.disabled = !on; });
  }

  // ---------- composer ----------
  const idea = $("idea");
  function autoGrow(t, max) { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight + 2, max) + "px"; }
  function updateCount() {
    const n = idea.value.length;
    $("count").textContent = `${n} / ${MAX_CHARS}`;
    $("count").classList.toggle("over", n > MAX_CHARS);
  }
  idea.addEventListener("input", () => { updateCount(); autoGrow(idea, 280); hint(""); });
  // Enter checks the idea. Shift+Enter adds a new line.
  idea.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("ideaForm").requestSubmit(); } });

  // Mirrors core/guard.py so obvious problems never cost a request. The server checks again.
  const FILLER_SET = new Set([
    "a", "an", "the", "app", "application", "website", "site", "tool", "platform",
    "thing", "things", "something", "project", "idea", "ai", "ml", "using", "with", "for",
    "that", "which", "is", "it", "my", "make", "build", "create", "want", "to",
    "i", "we", "of", "and", "or", "in", "on", "web", "mobile", "simple", "cool",
    "new", "good", "best", "people", "users", "user", "everyone", "some", "like",
    "based", "powered", "smart", "system", "software", "program", "bot", "do",
    "nice", "very", "great", "awesome", "fine", "bad", "okay", "ok", "test", "testing",
    "stuff", "yeah", "yes", "no", "hello", "world", "really",
    "wassup", "waassup", "whassup", "wazzup", "whatsup", "wasup", "sup",
    "hey", "hi", "says", "say", "said", "shows", "show", "displays", "display",
    "plays", "play", "clicks", "click", "just", "only", "simply", "where", "how", "what",
    "who", "whom", "whose", "when", "why", "let", "lets", "out", "into", "from",
    "about", "by", "at", "up", "down", "off", "over", "under", "get", "gets", "got",
    "give", "gives", "take", "takes", "put", "puts", "go", "goes", "went", "come",
    "comes", "came", "see", "saw", "know", "knows", "think", "thinks", "look", "looks",
  ]);
  const GITHUB_URL_RE = /(?:https?:\/\/)?(?:www\.)?github\.com\/([a-zA-Z0-9_.-]+)\/([a-zA-Z0-9_.-]+)/i;
  const TRIVIAL_RE = /^(?:[\w\s]{0,20}\s+)?(?:a\s+)?(?:website|site|app|tool|page|program|bot)\s+(?:that|which)?\s*(?:just\s+|only\s+)?(?:says|displays|shows|plays|speaks|prints|tells|outputs)\s+[\w\s]{1,30}$/i;
  const QUESTION_RE = /^(?:who|why|when|where|what|how(?:\s+come)?)\s+[^.?!\n]{2,120}\??$/i;
  const PRODUCT_WORDS_RE = /\b(?:app|application|website|site|platform|tool|software|system|extension|plugin|bot|cli|api|service|dashboard|tracker|generator|manager|engine|client)\b/i;
  const normW = (w) => w.toLowerCase().replace(/(\p{L})\1+/gu, "$1");

  function localCheck(text) {
    const t = text.trim();
    if (!t) return "Type or say your idea first. One to three sentences is enough.";
    if (t.length > MAX_CHARS) return `Keep it under ${MAX_CHARS} characters (now ${t.length}). Cut it to who it helps and what it does.`;
    if (/^https?:\/\/\S+$/i.test(t) || (GITHUB_URL_RE.test(t) && t.split(/\s+/).length <= 6)) return "";
    if (TRIVIAL_RE.test(t)) return "That's too trivial to search. What practical problem does it solve, and for whom?";
    if (QUESTION_RE.test(t) && !PRODUCT_WORDS_RE.test(t)) return "That looks like a question or phrase, not a project idea. What specific tool or app do you want to build?";
    const letters = [...t].filter((c) => /\p{L}/u.test(c));
    const nonLatin = letters.filter((c) => c.codePointAt(0) > 0x24f).length / Math.max(1, letters.length);
    if (nonLatin < 0.3) {
      const words = t.toLowerCase().match(/\p{L}+/gu) || [];
      const wordsNorm = words.map(normW);
      if (t.length < 20 || words.length < 4) return "Add a bit more. Who is it for, and what does it do that they can't do today?";
      const content = words.filter((w, i) => !FILLER_SET.has(w) && !FILLER_SET.has(wordsNorm[i]) && w.length > 2);
      if (new Set(wordsNorm).size < 4 || new Set(content.map(normW)).size < 3) return "That's too vague or repetitive. What specific problem does it solve, and for whom?";
    }
    return "";
  }

  // ---------- rival screenshot: pick, paste, or drop ----------
  const shotLabelEl = document.querySelector('label[for="shot"]');
  let shotUrl = "";
  function setShot(f) {
    if (!f) return resetShot();
    if (!/^image\/(png|jpeg|webp)$/.test(f.type)) { resetShot(); return hint("That file isn't a PNG, JPEG or WebP image. The check will run on text only.", true); }
    if (f.size > MAX_IMAGE) { resetShot(); return hint("That screenshot is over 5 MB. Crop it or take a smaller one.", true); }
    state.image = f;
    if (shotUrl) URL.revokeObjectURL(shotUrl);
    shotUrl = URL.createObjectURL(f);
    $("shotImg").src = shotUrl;
    $("shotName").textContent = f.name || "Pasted image";
    $("shotPreview").hidden = false;
    $("shotLabel").textContent = "Replace screenshot";
    shotLabelEl.classList.add("has-file");
    hint("");
  }
  function resetShot() {
    $("shot").value = "";
    state.image = null;
    if (shotUrl) { URL.revokeObjectURL(shotUrl); shotUrl = ""; }
    $("shotImg").removeAttribute("src");
    $("shotPreview").hidden = true;
    $("shotLabel").textContent = "Rival screenshot";
    shotLabelEl.classList.remove("has-file");
  }
  shotLabelEl.tabIndex = 0;
  shotLabelEl.setAttribute("role", "button");
  shotLabelEl.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("shot").click(); } });
  $("shot").addEventListener("change", (e) => setShot(e.target.files && e.target.files[0]));
  $("shotClear").addEventListener("click", () => { resetShot(); idea.focus(); });
  idea.addEventListener("paste", (e) => {
    const f = [...((e.clipboardData && e.clipboardData.files) || [])].find((x) => x.type.startsWith("image/"));
    if (f) { e.preventDefault(); setShot(f); }
  });
  const form = $("ideaForm");
  ["dragenter", "dragover"].forEach((t) => form.addEventListener(t, (e) => { if ([...e.dataTransfer.types].includes("Files")) { e.preventDefault(); form.classList.add("drop"); } }));
  ["dragleave", "drop"].forEach((t) => form.addEventListener(t, () => form.classList.remove("drop")));
  form.addEventListener("drop", (e) => { const f = e.dataTransfer.files && e.dataTransfer.files[0]; if (f) { e.preventDefault(); setShot(f); } });

  // Saved results made under older safety rules are never replayed.
  const isCurrent = (r) => !!r && !!state.health && r.safety_version === state.health.safety_version;
  const normIdea = (t) => (t || "").toLowerCase().split(/\s+/).filter(Boolean).join(" ");

  // The composer hides once a check starts; the idea stays visible as a card.
  function showComposer(show) {
    $("ideaForm").hidden = !show;
    document.querySelector(".hero").hidden = !show; // the banner belongs to the start screen only
    $("aside").hidden = !show;
    $("ideaCard").hidden = show;
    if (show) { autoGrow(idea, 280); idea.focus(); idea.setSelectionRange(idea.value.length, idea.value.length); }
  }
  // Same rule as core/guard.title_from_text: first words of the idea until the real title arrives.
  function quickTitle(text, n = 6) {
    const ws = (text || "").match(/[\p{L}\p{N}'+.-]+/gu) || [];
    while (ws.length && /^(a|an|the|i|we|my|want|to|build|make|create)$/i.test(ws[0])) ws.shift();
    const t = ws.slice(0, n).join(" ");
    return t ? t[0].toUpperCase() + t.slice(1) + (ws.length > n ? "…" : "") : "New check";
  }
  function setHeading(title, name = "") {
    $("ideaTitle").textContent = title || "New check";
    $("ideaName").textContent = name;
    $("ideaName").hidden = !name || (title || "").toLowerCase() === name.toLowerCase();
    $("topTitle").textContent = title || "New check";
    document.title = title && title !== "New check" ? `${title} · Already Built?` : "Already Built?";
  }
  function setIdeaCard(text, meta = "", canRerun = false) {
    $("ideaText").textContent = text;
    $("ideaMeta").textContent = meta;
    $("rerun").hidden = !canRerun;
    if (!state.result) setHeading(quickTitle(text));
  }
  // Any action that replaces the current check stops watching the old one.
  function supersede() {
    state.runToken++;
    state.jobId = "";
    if (state.busy) endRun();
    if (tts.ok) speechSynthesis.cancel();
  }
  $("editIdea").addEventListener("click", () => { supersede(); $("notice").hidden = true; showComposer(true); });
  function newCheck() {
    supersede();
    idea.value = ""; updateCount(); resetShot(); hint("");
    state.result = null;
    $("result").hidden = true; $("notice").hidden = true;
    state.historyId = "";
    setHeading("New check");
    showComposer(true);
    renderHistory();
    closeSideOnMobile();
  }
  $("newIdea").addEventListener("click", newCheck);
  $("newSide").addEventListener("click", newCheck);
  $("rerun").addEventListener("click", () => runCheck(true));

  async function runCheck(force = false) {
    if (state.busy) return;
    const text = idea.value.trim();
    const problem = localCheck(text);
    if (problem) { showComposer(true); hint(problem, true); return; }

    // Same idea, no new screenshot, checked in this browser before: show that result. No second run.
    if (!force && !state.image) {
      const prev = store.get(HISTORY_KEY, []).find((h) => normIdea(h.idea) === normIdea(text) && isCurrent(h.result));
      if (prev && prev.result) {
        return openHistory(prev, `Same idea as your check on ${fmtDate(prev.at)}. Showing that result.`);
      }
    }
    supersede();
    state.historyId = "";
    state.result = null;
    const token = state.runToken;
    const fd = new FormData();
    fd.append("idea", text);
    if (state.image) fd.append("image", state.image, state.image.name || "screenshot.png");
    if (force) fd.append("force", "true");
    setIdeaCard(text, state.image ? `With rival screenshot: ${state.image.name || "pasted image"}` : "");
    showComposer(false);
    startRun();
    try {
      const { job_id } = await api("/api/check", { method: "POST", body: fd });
      if (token !== state.runToken) return;
      state.jobId = job_id;
      await poll(job_id, token);
    } catch (err) {
      if (token !== state.runToken) return;
      endRun();
      const sub = err.status === 429 ? "Limits keep this tool free for everyone." : err.status === 503 ? "" : "Your idea is still here. Press Run again when ready.";
      setIdeaCard(text, "", true);
      showNotice(err.message, sub, true);
    }
  }
  $("ideaForm").addEventListener("submit", (e) => { e.preventDefault(); runCheck(false); });

  $("demoBtn").addEventListener("click", async () => {
    supersede();
    const token = state.runToken;
    try {
      const r = await api("/api/demo");
      if (token !== state.runToken) return;
      idea.value = r.idea || ""; updateCount();
      state.historyId = "";
      state.result = null;
      setIdeaCard(r.idea || "", "Saved example. Edit it or start a new check to try your own.");
      showComposer(false);
      showResult(r, { save: false });
    } catch (e) { showNotice(e.message, "", true); }
  });

  // ---------- progress ----------
  const DEFAULT_STAGES = [["read", "Reading your idea"], ["plan", "Planning search queries"], ["fetch", "Searching GitHub, Hugging Face and Hacker News"], ["rank", "Ranking matching projects"], ["report", "Writing your report"]];
  let timer = null;
  function startRun() {
    state.busy = true;
    const b = $("checkBtn");
    b.disabled = true;
    b.replaceChildren(el("span", { class: "spin", "aria-hidden": "true" }), "Checking…");
    hint("");
    $("notice").hidden = true;
    $("result").hidden = true;
    $("progress").hidden = false;
    renderStages(DEFAULT_STAGES, "read");
    const t0 = Date.now();
    clearInterval(timer);
    const tick = () => { const s = Math.round((Date.now() - t0) / 1000); $("elapsed").textContent = s < 45 ? `${s} s · usually under a minute` : `${s} s · still working, some sources are slow`; };
    tick();
    timer = setInterval(tick, 500);
  }
  function endRun() {
    state.busy = false;
    $("checkBtn").disabled = false;
    $("checkBtn").textContent = "Check idea";
    $("progress").hidden = true;
    clearInterval(timer);
    renderHistory();
  }
  function renderStages(stages, current, liveLabel = "") {
    const list = stages && stages.length ? stages : DEFAULT_STAGES;
    let idx = list.findIndex(([k]) => k === current);
    if (current === "queue") idx = 0;
    fill($("stageList"), ...list.map(([k, label], i) =>
      el("li", { class: i < idx ? "done" : i === idx ? "now" : "", "aria-current": i === idx ? "step" : null }, el("i", { "aria-hidden": "true" }),
        el("span", {}, current === "queue" && i === 0 ? "Waiting for a free slot" : label,
          i === idx && liveLabel && liveLabel !== label ? el("span", { class: "detail", text: liveLabel }) : null))));
  }
  async function poll(jobId, token) {
    const deadline = Date.now() + POLL_MAX_S * 1000;
    let misses = 0;
    while (Date.now() < deadline) {
      await sleep(POLL_MS);
      if (token !== state.runToken) return; // a newer action replaced this check
      let s;
      try { s = await api(`/api/check/${encodeURIComponent(jobId)}`); misses = 0; }
      catch (e) {
        if (token !== state.runToken) return;
        // A brief network blip shouldn't throw away a running check.
        if (e.network && ++misses < 6) { await sleep(1000 * misses); continue; }
        endRun();
        setIdeaCard(idea.value.trim(), "", true);
        return showNotice(e.status === 404 ? "This check expired on the server (it may have restarted)." : e.message, "Press Run again to start it over.", true);
      }
      if (token !== state.runToken) return;
      renderStages(s.stages || [], s.stage, s.detail || "");
      if (s.state === "done") { endRun(); return showResult(s.result, { save: true }); }
    }
    endRun();
    setIdeaCard(idea.value.trim(), "", true);
    showNotice("This check is taking too long.", "Press Run again, or open the saved example.", true);
  }

  function showNotice(main, sub = "", stop = false) {
    const n = $("notice");
    fill(n, el("p", { text: main }), sub ? el("p", { text: sub }) : null);
    n.classList.toggle("stop", stop);
    n.hidden = false;
  }

  // ---------- result ----------
  const SOURCE = { github: "GitHub", "hf-space": "HF Space", "hf-model": "HF Model", hn: "Show HN" };
  const UNIT = { github: "stars", "hf-space": "likes", "hf-model": "likes", hn: "points" };
  const LEVEL = { taken: "Already built", crowded: "Crowded", open: "No close match", unknown: "Incomplete" };
  const QUAD = {
    rival: "Direct rival",
    "same-problem": "Same problem, other approach",
    "same-build": "Same approach, other users",
    loose: "Loosely related",
  };

  function ageText(iso) {
    const t = Date.parse(iso || "");
    if (isNaN(t)) return "date unknown";
    const d = Math.max(0, Math.floor((Date.now() - t) / 86400000));
    if (d < 1) return "today";
    if (d < 31) return `${d} d ago`;
    if (d < 365) return `${Math.floor(d / 30)} mo ago`;
    return `${(d / 365).toFixed(1)} y ago`;
  }

  function showResult(res, { save }) {
    if (!res || typeof res !== "object") return showNotice("The server sent an empty result.", "Press Run again.", true);
    const s = res.status;
    if (s && s !== "ok") {
      const soft = ["empty", "short", "vague", "long", "url_failed", "harmful"].includes(s);
      if (soft) { showComposer(true); hint(res.message, true); return; }
      const sub = s === "source_failed" ? [...(res.errors || [])].join(" ") + " Try again in a few minutes, or open the saved example." : "";
      if (s === "crashed" || s === "rank_failed") setIdeaCard(res.idea || idea.value.trim(), "", true);
      return showNotice(res.message || "Something went wrong. Try again.", sub, true);
    }
    if (res.cached_at) setIdeaCard(res.idea, `Same idea as a check from ${fmtDate(res.cached_at * 1000)}. Showing that result.`, true);
    else if (save) setIdeaCard(res.idea, "", true);
    state.result = res;
    state.chat = [];
    setHeading(res.title || quickTitle(res.idea), res.project_name || "");
    $("notice").hidden = true;
    $("result").hidden = false;

    const dn = $("demoNote");
    dn.hidden = !res.demo;
    if (res.demo) fill(dn, "Saved example for: ", el("b", { text: res.idea || "" }), res.demo_note ? [el("br"), res.demo_note] : null);

    const notes = [...new Set([...(res.warnings || []), ...(res.errors || [])])];
    fill($("warnings"), ...notes.map((w) => el("li", { text: w })));

    const v = res.verdict || { level: "unknown", title: "No verdict", text: "This result has no verdict. Run the check again." };
    const level = LEVEL[v.level] ? v.level : "unknown";
    $("verdict").className = `verdict v-${level}`;
    $("verdictBadge").textContent = LEVEL[level];
    $("verdictTitle").textContent = v.title || "";
    $("verdictText").textContent = v.text || "";

    renderFacts(res);
    const claims = [];
    if (res.core_claim) claims.push(el("p", { class: "claim" }, el("b", { text: "Read as" }), res.core_claim));
    if (res.rival) claims.push(el("p", { class: "claim" }, el("b", { text: "Your screenshot" }), res.rival));
    fill($("claims"), ...claims);

    renderReport(res);
    renderRows(res);
    renderMap(res);
    renderHow(res);
    renderChat();
    if (save) { saveHistory(res); buddy().quip(level); } // a fresh result gets a one-liner
    renderHistory();
    $("verdict").scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "start" });
    $("verdict").focus({ preventScroll: true });
  }

  // The four numbers that decide "quit or build", all straight from the data.
  function renderFacts(res) {
    const top = res.top || [];
    const rivals = top.filter((p) => p.quadrant === "rival");
    const inactive = top.filter((p) => p.stale || p.archived).length;
    const best = top.length ? Math.max(...top.map((p) => num(p.score))) : 0;
    const facts = [
      [rivals.length, rivals.length === 1 ? "direct rival" : "direct rivals", rivals.length > 0],
      [top.length, top.length === 1 ? "close match" : "close matches", false],
      [inactive, "inactive 1y+", false],
      [top.length ? best.toFixed(2) : "–", "best similarity", best >= 0.7],
    ];
    fill($("facts"), ...facts.map(([n, label, hot]) => el("div", { class: hot ? "hot" : "" }, el("b", { text: String(n) }), el("span", { text: label }))));
  }

  function citeLinks(cites, rep, top) {
    const byId = Object.fromEntries((top || []).map((c) => [c.id, c]));
    return (cites || []).map((pid) => {
      const c = byId[(rep.ids || {})[pid]];
      return c ? el("a", { class: "cite", href: safeUrl(c.url), target: "_blank", rel: "noopener noreferrer", title: c.name, text: pid }) : null;
    });
  }

  function renderReport(res) {
    const rep = res.report;
    const box = $("report");
    if (!rep) { fill(box, el("p", { class: "empty", text: "No report for this check." })); $("reportMeta").textContent = ""; return; }
    const sections = [["overlap", "What already exists"], ["differs", "What your idea states differently"], ["gaps", "Weak spots in existing projects"], ["avoid", "Reality checks"]];
    const nodes = sections.filter(([k]) => Array.isArray(rep[k]) && rep[k].length).map(([k, title]) =>
      el("section", { class: `sec sec-${k}` }, el("h3", { text: title }),
        el("ul", {}, rep[k].map((it) => el("li", {}, it.text, citeLinks(it.cites, rep, res.top))))));
    if (rep.next_step) nodes.push(el("div", { class: "next" }, el("h3", { text: "Do this next" }), el("p", { text: rep.next_step })));
    fill(box, ...(nodes.length ? nodes : [el("p", { class: "empty", text: "The report came back empty." })]));
    const meta = [];
    if (res.report_note) meta.push(res.report_note);
    else meta.push("Written only from the projects listed below. Tags like P1 open the source.");
    if (rep.dropped_citations) meta.push(`Removed ${rep.dropped_citations} reference(s) to projects that were not in the list.`);
    $("reportMeta").textContent = meta.join(" ");
  }

  function blocks(score, hot) {
    const on = Math.max(0, Math.min(10, Math.round(score * 10)));
    return el("span", { class: hot ? "blocks hot" : "blocks", "aria-hidden": "true" },
      Array.from({ length: 10 }, (_, i) => el("i", { class: i < on ? "on" : "" })));
  }

  function renderRows(res) {
    const top = res.top || [];
    const c = res.counts || {};
    $("countNote").textContent = top.length ? `${top.length} of ${c.unique || 0} unique results` : "";
    const found = c.by_source || {};
    const inTop = (keys) => top.filter((p) => keys.some((k) => (p.source || "").startsWith(k))).length;
    const mix = [["GitHub", ["github"], "github"], ["Hugging Face", ["hf"], "hf"], ["Show HN", ["hn"], "hn"]]
      .map(([label, keys, k]) => `${label} ${inTop(keys)} shown of ${found[k] ?? "?"} found`);
    $("rowsNote").dataset.mix = mix.join(" · ");
    if (!top.length) {
      fill($("rows"), el("li", { class: "empty", text: (res.partial || []).length
        ? `Nothing passed the similarity bar, but ${res.partial.join(", ")} couldn't be searched. Run it again before trusting this.`
        : "Nothing passed the similarity bar on GitHub, Hugging Face or Show HN. Closed apps and startups aren't searched, so look there too." }));
      $("rowsNote").textContent = "";
      return;
    }
    fill($("rows"), ...top.map((p, i) => {
      const score = num(p.score);
      const flags = [];
      if (p.quadrant === "rival") flags.push(el("span", { class: "flag hot", text: "direct rival" }));
      else if (QUAD[p.quadrant] && p.quadrant !== "loose") flags.push(el("span", { class: "flag warm", text: QUAD[p.quadrant].toLowerCase() }));
      if (p.archived) flags.push(el("span", { class: "flag dead", text: "archived" }));
      else if (p.stale) flags.push(el("span", { class: "flag dead", text: "inactive 1y+" }));
      if (p.low_confidence) flags.push(el("span", { class: "flag dead", text: "no description" }));
      const desc = p.description || (p.readme || "").slice(0, 180);
      return el("li", { class: "row" },
        el("span", { class: "rank", text: `P${i + 1}` }),
        el("div", {},
          el("a", { href: safeUrl(p.url), target: "_blank", rel: "noopener noreferrer", text: p.name }),
          el("p", { text: desc || "No description." }),
          el("div", { class: "meta" },
            el("span", { class: `src-tag ${p.source === "hn" ? "hn" : (p.source || "").startsWith("hf") ? "hf" : ""}`, text: SOURCE[p.source] || p.source }),
            el("span", { text: `${num(p.stars)} ${UNIT[p.source] || "stars"}` }),
            el("span", { text: p.source === "hn" ? `posted ${ageText(p.updated_at)}` : `updated ${ageText(p.updated_at)}` }),
            flags)),
        el("div", { class: "sim", title: `Similarity ${score.toFixed(2)} (0 to 1)` }, blocks(score, p.quadrant === "rival"), el("small", { text: `${score.toFixed(2)} similar` })));
    }));
    $("rowsNote").textContent = ($("rowsNote").dataset.mix ? $("rowsNote").dataset.mix + ". " : "") + "Similarity is a text match between your idea and each project's description and README, from 0 to 1. Under 0.35 counts as unrelated and is hidden. It measures overlap in wording and purpose, not how good a project is.";
  }

  // Quadrant chart: x = same users and problem, y = same features and approach. Both are real scores.
  function renderMap(res) {
    const top = res.top || [];
    const pts = (res.map || []).filter((p) => isFinite(p.x) && isFinite(p.y));
    const block = $("mapBlock");
    const link = document.querySelector('#jump a[href="#mapBlock"]');
    const tops = pts.filter((p) => p.kind === "top" && p.pid);
    if (!top.length || !tops.length) { block.hidden = true; if (link) link.hidden = true; return; }
    block.hidden = false; if (link) link.hidden = false;

    const split = num(res.quadrant_split, 0.45);
    const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
    const lo = Math.max(-0.2, Math.min(0.15, Math.min(...xs, ...ys) - 0.05));
    const hi = Math.min(1, Math.max(0.8, Math.max(...xs, ...ys) + 0.05));
    const W = 640, H = 420, L = 44, R = 16, T = 16, B = 44;
    const sx = (v) => L + ((v - lo) / (hi - lo)) * (W - L - R);
    const sy = (v) => H - B - ((v - lo) / (hi - lo)) * (H - T - B);
    const tip = $("mapTip");
    const describe = (p) => [el("b", { text: `${p.pid} ${p.name}` }), ` · ${QUAD[p.quadrant] || ""} · problem ${p.x.toFixed(2)}, approach ${p.y.toFixed(2)}`];
    const defaultTip = "Hover or focus a point for details. Click to open the project.";

    const ticks = [];
    for (let v = Math.ceil(lo * 10) / 10; v <= hi + 1e-9; v += 0.2) {
      const r = Math.round(v * 10) / 10;
      ticks.push(svg("text", { x: sx(r), y: H - B + 16, class: "tick", "text-anchor": "middle", text: r.toFixed(1) }));
      ticks.push(svg("text", { x: L - 8, y: sy(r) + 3, class: "tick", "text-anchor": "end", text: r.toFixed(1) }));
    }
    const others = pts.filter((p) => p.kind !== "top").map((p) => svg("circle", { cx: sx(p.x), cy: sy(p.y), r: 3, class: "pt-other" }));
    const dots = tops.sort((a, b) => a.score - b.score).map((p) => {
      const right = sx(p.x) < W - 60;
      return svg("g", {
        class: p.quadrant === "rival" ? "pt rival" : "pt", tabindex: "0", role: "link",
        "aria-label": `${p.pid} ${p.name}: ${QUAD[p.quadrant] || ""}. Problem match ${p.x.toFixed(2)}, approach match ${p.y.toFixed(2)}.`,
        onmouseenter: () => fill(tip, describe(p)), onfocus: () => fill(tip, describe(p)),
        onmouseleave: () => { tip.textContent = defaultTip; },
        onclick: () => window.open(safeUrl(p.url), "_blank", "noopener"),
        onkeydown: (e) => { if (e.key === "Enter") window.open(safeUrl(p.url), "_blank", "noopener"); },
      },
      svg("circle", { cx: sx(p.x), cy: sy(p.y), r: 6 }),
      svg("text", { x: sx(p.x) + (right ? 10 : -10), y: sy(p.y) + 4, "text-anchor": right ? "start" : "end", text: p.pid }));
    });

    const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Chart of ${tops.length} close projects by problem match and approach match.` },
      svg("rect", { x: sx(split), y: T, width: W - R - sx(split), height: sy(split) - T, class: "q-rival" }),
      svg("line", { x1: sx(split), x2: sx(split), y1: T, y2: H - B, class: "q-line" }),
      svg("line", { x1: L, x2: W - R, y1: sy(split), y2: sy(split), class: "q-line" }),
      svg("line", { x1: L, x2: W - R, y1: H - B, y2: H - B, class: "axis" }),
      svg("line", { x1: L, x2: L, y1: T, y2: H - B, class: "axis" }),
      svg("text", { x: W - R - 8, y: T + 16, class: "q-label hot", "text-anchor": "end", text: "Direct rivals" }),
      svg("text", { x: L + 8, y: T + 16, class: "q-label", text: "Same approach, other users" }),
      svg("text", { x: W - R - 8, y: H - B - 8, class: "q-label", "text-anchor": "end", text: "Same problem, other approach" }),
      svg("text", { x: L + 8, y: H - B - 8, class: "q-label", text: "Loosely related" }),
      ticks, others, dots,
      svg("text", { x: (L + W - R) / 2, y: H - 8, class: "ax-label", "text-anchor": "middle", text: "Same users and problem →" }),
      svg("text", { x: 12, y: (T + H - B) / 2, class: "ax-label", "text-anchor": "middle", transform: `rotate(-90 12 ${(T + H - B) / 2})`, text: "Same features and approach →" }));
    fill($("map"), chart);

    const rivals = tops.filter((p) => p.quadrant === "rival").length;
    $("mapSummary").textContent = rivals
      ? `${rivals} of ${tops.length} close projects sit in the top-right: same users, same approach. Those are the ones to beat.`
      : `None of the ${tops.length} close projects match both your users and your approach. Each overlaps on one side only.`;
    tip.textContent = defaultTip;
  }

  function renderHow(res) {
    const m = res.models || {};
    const c = res.counts || {};
    const t = res.timings || {};
    fill($("how"), 
      el("p", {}, el("b", { text: "Searched for " }), `(${res.query_source || "n/a"}): `, ...(res.queries || []).flatMap((q, i) => i ? [", ", el("code", { text: q })] : [el("code", { text: q })])),
      el("p", { text: `Fetched ${c.fetched || 0} results from GitHub, Hugging Face and Hacker News. ${c.unique || 0} left after removing forks, mirrors and repeats. ${c.kept || 0} passed the similarity bar.` }),
      (res.partial || []).length ? el("p", { text: `Not searched this time: ${res.partial.join(", ")}.` }) : null,
      el("p", { text: `Models: plan ${m.plan || "-"}, ranking ${m.embed || "-"} (local), report ${m.report || "-"}.` }),
      Object.keys(t).length ? el("p", { text: "Time: " + Object.entries(t).map(([k, v]) => `${k} ${v}s`).join(", ") }) : null,
    );
  }

  // ---------- history sidebar (this browser only) ----------
  const newId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  function loadHistory() {
    let list = store.get(HISTORY_KEY, []);
    if (!Array.isArray(list)) { store.del(HISTORY_KEY); return []; }
    list = list.filter((h) => h && typeof h.idea === "string" && h.result && typeof h.result === "object");
    let changed = false;
    for (const h of list) {
      if (!h.id) { h.id = newId(); changed = true; } // entries saved before ids existed
      if (!Array.isArray(h.chat)) h.chat = [];
      if (!("verdict" in h)) { // old entries stored the verdict as their title
        h.verdict = h.title || "";
        h.title = h.result.title || quickTitle(h.idea);
        h.level = (h.result.verdict || {}).level || "";
        changed = true;
      }
    }
    if (state.health) {
      const kept = list.filter((h) => isCurrent(h.result));
      if (kept.length !== list.length) { list = kept; changed = true; }
    }
    if (changed) writeHistory(list);
    return list;
  }
  function writeHistory(list) {
    const out = list.slice(0, HISTORY_MAX);
    // Results can be large; drop the oldest until it fits the storage quota.
    while (out.length && !store.set(HISTORY_KEY, out)) out.pop();
  }
  function saveHistory(res) {
    if (!res || res.demo || !res.idea) return;
    const list = loadHistory().filter((h) => normIdea(h.idea) !== normIdea(res.idea));
    const v = res.verdict || {};
    const entry = { id: newId(), idea: res.idea, title: res.title || quickTitle(res.idea), project_name: res.project_name || "",
      level: v.level || "", verdict: v.title || "", at: Date.now(), result: res, chat: [] };
    list.unshift(entry);
    writeHistory(list);
    state.historyId = entry.id;
  }
  function saveChat() {
    if (!state.historyId) return;
    const list = loadHistory();
    const h = list.find((x) => x.id === state.historyId);
    if (!h) return;
    h.chat = state.chat.slice(-40);
    writeHistory(list);
  }
  function openHistory(h, meta) {
    supersede();
    state.historyId = h.id;
    state.result = null;
    idea.value = h.idea; updateCount();
    setIdeaCard(h.idea, meta || `Your check from ${fmtDate(h.at)}.`, true);
    showComposer(false);
    showResult(h.result, { save: false });
    // Bring back the conversation that belongs to this check.
    state.chat = (h.chat || []).filter((m) => m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string");
    for (const m of state.chat) addMsg(m.role === "user" ? "me" : "bot", m.content, { scroll: false });
    if (state.chat.length) fill($("suggest"));
    closeSideOnMobile();
  }
  function groupOf(at) {
    const day = 86400000;
    const start = new Date(); start.setHours(0, 0, 0, 0);
    const t0 = start.getTime();
    if (at >= t0) return "Today";
    if (at >= t0 - day) return "Yesterday";
    if (at >= t0 - 7 * day) return "Previous 7 days";
    if (at >= t0 - 30 * day) return "Previous 30 days";
    return "Older";
  }
  function renderHistory() {
    const list = loadHistory();
    const q = normIdea($("historySearch").value);
    const shown = q ? list.filter((h) => normIdea(`${h.title} ${h.project_name} ${h.idea}`).includes(q)) : list;
    const nodes = [];
    let group = "";
    for (const h of shown) {
      const g = groupOf(h.at);
      if (g !== group) { group = g; nodes.push(el("p", { class: "h-group", text: g })); }
      const active = h.id === state.historyId;
      nodes.push(el("div", { class: active ? "h-item active" : "h-item" },
        el("button", { type: "button", class: "h-open", title: h.idea, "aria-current": active ? "true" : null, onclick: () => openHistory(h) },
          el("span", { class: `h-dot ${h.level || ""}`, "aria-hidden": "true" }),
          el("span", { class: "h-text" },
            el("span", { class: "h-title", text: h.title || quickTitle(h.idea) }),
            el("span", { class: "h-sub", text: [h.project_name !== h.title ? h.project_name : "", h.verdict].filter(Boolean).join(" · ") || h.idea }))),
        el("button", { type: "button", class: "h-del", "aria-label": `Delete ${h.title || "check"}`, title: "Delete", onclick: () => deleteHistory(h.id) }, "×")));
    }
    fill($("historyList"), nodes);
    $("historyEmpty").hidden = shown.length > 0;
    $("historyEmpty").textContent = q && list.length ? "No checks match that search." : "Your checks appear here. They are saved only in this browser.";
    $("historyClear").hidden = !list.length;
  }
  function deleteHistory(id) {
    writeHistory(loadHistory().filter((h) => h.id !== id));
    if (state.historyId === id) state.historyId = "";
    renderHistory();
  }
  $("historySearch").addEventListener("input", renderHistory);
  $("historyClear").addEventListener("click", () => {
    if (!confirm("Delete all saved checks and their chats from this browser?")) return;
    store.del(HISTORY_KEY);
    state.historyId = "";
    renderHistory();
  });

  // ---------- sidebar open / collapse ----------
  const app = $("app");
  const narrowMq = matchMedia("(max-width: 900px)");
  function setSide(open) {
    if (narrowMq.matches) {
      app.classList.toggle("side-open", open);
      app.classList.remove("side-collapsed");
      $("scrim").hidden = !open;
      if (open) $("newSide").focus();
    } else {
      app.classList.toggle("side-collapsed", !open);
      store.set(SIDE_KEY, open ? "open" : "closed");
    }
    $("sideOpen").setAttribute("aria-expanded", String(open));
  }
  function closeSideOnMobile() { if (narrowMq.matches && app.classList.contains("side-open")) setSide(false); }
  $("sideOpen").addEventListener("click", () => setSide(true));
  $("sideClose").addEventListener("click", () => { setSide(false); $("sideOpen").focus(); });
  $("scrim").addEventListener("click", () => setSide(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && app.classList.contains("side-open")) setSide(false); });
  narrowMq.addEventListener("change", () => {
    app.classList.remove("side-open");
    $("scrim").hidden = true;
    app.classList.toggle("side-collapsed", !narrowMq.matches && store.get(SIDE_KEY, "open") === "closed");
  });
  if (!narrowMq.matches && store.get(SIDE_KEY, "open") === "closed") app.classList.add("side-collapsed");

  // ---------- text to speech ----------
  const tts = {
    ok: "speechSynthesis" in window && "SpeechSynthesisUtterance" in window,
    voice: null,
    btn: null,
    pickVoice() {
      if (!this.ok) return;
      const vs = speechSynthesis.getVoices();
      const lang = (navigator.language || "en").slice(0, 2);
      const mine = vs.filter((v) => v.lang && v.lang.toLowerCase().startsWith(lang));
      const pool = mine.length ? mine : vs.filter((v) => /^en/i.test(v.lang));
      this.voice = pool.find((v) => /natural|neural|online/i.test(v.name)) || pool.find((v) => /google/i.test(v.name)) || pool.find((v) => v.localService) || pool[0] || null;
    },
    clean(text) {
      return text.replace(/\bP(\d+)\b/g, "project $1").replace(/https?:\/\/\S+/g, "").replace(/[*_#`>|]+/g, " ").replace(/\s+/g, " ").trim();
    },
    stop() {
      speechSynthesis.cancel();
      if (this.btn) setSpeakBtn(this.btn, false);
      this.btn = null;
    },
    speak(text, btn) {
      if (!this.ok) return;
      const same = btn && this.btn === btn;
      if (speechSynthesis.speaking || speechSynthesis.pending) { this.stop(); if (same) return; }
      // Chrome cuts long utterances; speak sentence by sentence.
      const parts = this.clean(text).match(/[^.!?]+[.!?]*/g) || [];
      if (!parts.length) return;
      this.btn = btn || null;
      if (btn) setSpeakBtn(btn, true);
      parts.forEach((p, i) => {
        const u = new SpeechSynthesisUtterance(p.trim());
        if (this.voice) u.voice = this.voice;
        u.rate = 1.02;
        u.onstart = () => buddy().say(p.trim());
        if (i === parts.length - 1) u.onend = () => { if (this.btn === btn && btn) { setSpeakBtn(btn, false); this.btn = null; } };
        u.onerror = () => { if (btn) setSpeakBtn(btn, false); if (this.btn === btn) this.btn = null; };
        speechSynthesis.speak(u);
      });
    },
  };
  function setSpeakBtn(btn, on) { btn.setAttribute("aria-pressed", on ? "true" : "false"); btn.querySelector("span").textContent = on ? "Stop" : "Read aloud"; }
  if (tts.ok) { tts.pickVoice(); speechSynthesis.onvoiceschanged = () => tts.pickVoice(); }
  else $("speakReport").hidden = true;

  $("speakReport").addEventListener("click", () => {
    const r = state.result;
    if (!r) return;
    const rep = r.report || {};
    const v = r.verdict || {};
    const lines = [(v.title || "") + ".", v.text || ""];
    for (const [k, t] of [["gaps", "Weak spots in existing projects."], ["avoid", "Reality checks."]]) {
      if ((rep[k] || []).length) lines.push(t, ...rep[k].map((i) => i.text));
    }
    if (rep.next_step) lines.push("Do this next.", rep.next_step);
    tts.speak(lines.join(" "), $("speakReport"));
  });

  // ---------- speech to text ----------
  // Chrome/Edge/Safari: the browser's own SpeechRecognition (live text).
  // Firefox and SR failures: record here, transcribe on the server with Whisper.
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const sttLang = () => { const v = $("sttLang").value; return v === "auto" ? "" : v; };
  const BCP47 = { en: navigator.language && navigator.language.startsWith("en-") ? navigator.language : "en-US", hi: "hi-IN", te: "te-IN", ta: "ta-IN" };
  const savedLang = store.get(LANG_KEY, "en");
  $("sttLang").value = [...$("sttLang").options].some((o) => o.value === savedLang) ? savedLang : "en";
  $("sttLang").addEventListener("change", (e) => store.set(LANG_KEY, e.target.value));
  const mics = [];

  function makeMic(btn, target, onDone) {
    let rec = null, chunks = [], stream = null, started = 0, tick = null, srInst = null, analyser = null, audioCtx = null, raf = 0, srBroken = false;
    const label = btn.querySelector("span");
    const idleText = label.textContent;
    const levelEl = el("span", { class: "level", "aria-hidden": "true" }, Array.from({ length: 8 }, () => el("i")));
    const serverStt = () => !!(state.health && state.health.groq && window.MediaRecorder && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);

    function cleanup() {
      buddy().listening(false);
      btn.setAttribute("aria-pressed", "false");
      label.textContent = idleText;
      levelEl.remove();
      clearInterval(tick); cancelAnimationFrame(raf);
      if (stream) stream.getTracks().forEach((t) => t.stop());
      if (audioCtx) audioCtx.close().catch(() => {});
      stream = null; analyser = null; audioCtx = null;
    }
    function insert(text) {
      const cur = target.value.trim();
      target.value = (cur ? cur + " " : "") + text.trim();
      target.dispatchEvent(new Event("input"));
      onDone(text, "");
    }
    function meter() {
      if (!analyser) return;
      const data = new Uint8Array(analyser.fftSize);
      analyser.getByteTimeDomainData(data);
      let peak = 0;
      for (const v of data) peak = Math.max(peak, Math.abs(v - 128));
      const on = Math.min(8, Math.round((peak / 64) * 8));
      [...levelEl.children].forEach((b, i) => b.classList.toggle("on", i < on));
      raf = requestAnimationFrame(meter);
    }

    function useBrowserSR() {
      try { srInst = new SR(); } catch { srBroken = true; return startServerSTT(); }
      srInst.lang = BCP47[sttLang()] || navigator.language || "en-US";
      srInst.interimResults = true;
      srInst.continuous = true;
      const base = target.value.trim();
      let failed = "";
      srInst.onresult = (e) => {
        let finalStr = "", interimStr = "";
        for (let i = 0; i < e.results.length; i++) {
          const r = e.results[i];
          if (r.isFinal) finalStr += r[0].transcript + " ";
          else interimStr += r[0].transcript;
        }
        target.value = (base ? base + " " : "") + (finalStr + interimStr).trim();
        target.dispatchEvent(new Event("input"));
        target.scrollTop = target.scrollHeight;
      };
      srInst.onerror = (e) => {
        if (e.error === "no-speech" || e.error === "aborted") return;
        failed = e.error;
      };
      srInst.onend = () => {
        srInst = null;
        cleanup();
        if (!failed) return onDone(target.value, "");
        if (failed === "not-allowed") return onDone(null, "Microphone blocked. Allow it in the address bar, or type instead.");
        // Brave, some Edge builds and offline Chrome can't reach the speech service: record and send to the server instead.
        srBroken = true;
        if (serverStt()) { onDone(null, ""); return startServerSTT(); }
        onDone(null, "Speech input isn't working in this browser. Type instead.");
      };
      try {
        srInst.start();
        btn.setAttribute("aria-pressed", "true");
        label.textContent = "Listening… click to stop";
        buddy().listening(true);
      } catch { srInst = null; srBroken = true; startServerSTT(); }
    }

    async function startServerSTT() {
      if (!serverStt()) return onDone(null, "Speech input isn't available here. Type instead, or use Chrome or Edge.");
      try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); }
      catch (e) { cleanup(); return onDone(null, e.name === "NotAllowedError" ? "Microphone blocked. Allow it in the address bar, or type instead." : "No microphone found. Type instead."); }
      const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"].find((m) => MediaRecorder.isTypeSupported(m)) || "";
      try { rec = new MediaRecorder(stream, mime ? { mimeType: mime } : {}); }
      catch { cleanup(); return onDone(null, "This browser can't record audio. Type instead."); }
      chunks = [];
      rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      rec.onstop = upload;
      rec.start();
      started = Date.now();
      try {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        analyser = audioCtx.createAnalyser(); analyser.fftSize = 512;
        audioCtx.createMediaStreamSource(stream).connect(analyser);
        meter();
      } catch { analyser = null; }
      btn.setAttribute("aria-pressed", "true");
      btn.append(levelEl);
      buddy().listening(true);
      const upd = () => {
        const s = Math.floor((Date.now() - started) / 1000);
        label.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")} · click to stop`;
        if (Date.now() - started > MAX_REC_MS) stop();
      };
      upd(); tick = setInterval(upd, 250);
    }

    function start() {
      mics.forEach((m) => m !== api_ && m.stop()); // one mic at a time
      if (SR && !srBroken) return useBrowserSR();
      return startServerSTT();
    }
    function stop() {
      if (srInst) { try { srInst.stop(); } catch { /* already stopped */ } return; }
      if (rec && rec.state !== "inactive") rec.stop();
    }

    async function upload() {
      const type = (rec && rec.mimeType) || "audio/webm";
      const blob = new Blob(chunks, { type });
      const dur = Date.now() - started;
      rec = null;
      cleanup();
      if (dur < 600 || blob.size < 1200) return onDone(null, "Too short. Click the mic, speak, then click again to stop.");
      label.textContent = "Transcribing…";
      btn.disabled = true;
      const fd = new FormData();
      fd.append("audio", blob, "speech." + (type.includes("mp4") ? "mp4" : type.includes("ogg") ? "ogg" : "webm"));
      // Without a language hint Whisper guesses, and short clips can come back in the wrong language.
      fd.append("language", sttLang());
      try {
        const { text } = await api("/api/transcribe", { method: "POST", body: fd });
        if (text) insert(text); else onDone(null, "Didn't catch any words. Try again closer to the mic.");
      } catch (e) {
        if (e.message === "no_server_stt") { if (state.health) state.health.groq = false; onDone(null, "Server speech is off. Type instead, or use Chrome or Edge."); }
        else onDone(null, e.message);
      } finally {
        btn.disabled = false;
        label.textContent = idleText;
      }
    }

    btn.addEventListener("click", () => (btn.getAttribute("aria-pressed") === "true" ? stop() : start()));
    const api_ = { stop: () => { if (btn.getAttribute("aria-pressed") === "true") stop(); } };
    mics.push(api_);
    return api_;
  }

  if (!SR && !window.MediaRecorder) { $("micBtn").hidden = true; $("chatMic").hidden = true; $("sttLang").parentElement.hidden = true; }
  makeMic($("micBtn"), idea, (_t, err) => { if (err) hint(err, true); else if (_t !== null) idea.focus(); });
  makeMic($("chatMic"), $("chatInput"), (_t, err) => { if (err) addMsg("err", err); else if (_t !== null) $("chatInput").focus(); });

  // ---------- chat ----------
  const SUGGEST = [
    "One small twist I could build this week",
    "A bigger pivot to a less crowded niche",
    "What's the smallest test I can ship?",
    "How is my idea different from P1?",
  ];
  function renderChat() {
    fill($("thread"), );
    const top = (state.result && state.result.top) || [];
    const qs = SUGGEST.filter((q) => top.length || !q.includes("P1"));
    fill($("suggest"), ...qs.map((q) => el("button", { type: "button", text: q, onclick: () => sendChat(q) })));
    applyChatAvailability();
  }
  // Plain text with light bold, code and bullets. Escaped first, so model output can't inject HTML.
  function miniMd(text) {
    const esc = (text || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    return esc
      .replace(/^#{1,6}\s*(.+)$/gm, "$1")
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/`([^`\n]+)`/g, "<code>$1</code>")
      .replace(/^\s*[*-]\s+/gm, "• ");
  }
  function addMsg(kind, text, { scroll = true } = {}) {
    const who = kind === "me" ? "You" : kind === "bot" ? "Advisor" : "Note";
    const body = el("div", { class: "msg" });
    if (kind === "bot") body.innerHTML = miniMd(text); else body.textContent = text;
    const li = el("li", { class: kind }, el("span", { class: "who", text: who }), body);
    if (kind === "bot" && tts.ok) {
      const b = el("button", { type: "button", class: "tool small ghost say", "aria-pressed": "false" }, el("span", { text: "Read aloud" }));
      b.addEventListener("click", () => tts.speak(text, b));
      li.append(b);
    }
    $("thread").append(li);
    if (scroll) li.scrollIntoView({ block: "nearest", behavior: reduceMotion() ? "auto" : "smooth" });
    return li;
  }
  async function sendChat(text) {
    const q = (text || "").trim();
    if (!q || state.chatBusy || !state.result) return;
    if (!chatOn()) return addMsg("err", "The advisor needs GROQ_API_KEY on the server.");
    const result = state.result;
    state.chatBusy = true;
    $("chatForm").setAttribute("aria-busy", "true");
    $("chatSend").disabled = true;
    fill($("suggest"), );
    $("chatInput").value = "";
    autoGrow($("chatInput"), 180);
    addMsg("me", q);
    state.chat.push({ role: "user", content: q.slice(0, 2000) });
    const wait = addMsg("err", "Thinking");
    wait.classList.add("wait");
    try {
      const body = { job_id: state.jobId, messages: state.chat.slice(-12) };
      if (!state.jobId || result.demo) body.result = result;
      const post = () => api("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      let r;
      try { r = await post(); }
      catch (e) {
        // Server restarted and lost the job: retry once with the result attached.
        if (e.status !== 400 || body.result) throw e;
        body.result = result;
        r = await post();
      }
      if (state.result !== result) return; // user moved on to another result
      wait.remove();
      state.chat.push({ role: "assistant", content: r.reply || "" });
      addMsg("bot", r.reply || "(empty reply)");
      saveChat();
      if ($("autoSpeak").checked) tts.speak(r.reply || "");
    } catch (e) {
      if (state.result !== result) return;
      wait.remove();
      state.chat.pop();
      addMsg("err", e.message);
      if (!$("chatInput").value) { $("chatInput").value = q; autoGrow($("chatInput"), 180); }
    } finally {
      state.chatBusy = false;
      $("chatForm").setAttribute("aria-busy", "false");
      applyChatAvailability();
    }
  }
  $("chatInput").addEventListener("input", () => autoGrow($("chatInput"), 180));
  $("chatInput").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendChat($("chatInput").value); } });
  $("chatForm").addEventListener("submit", (e) => { e.preventDefault(); sendChat($("chatInput").value); });
  $("autoSpeak").checked = !!store.get(SPEAK_KEY, false);
  $("autoSpeak").addEventListener("change", (e) => store.set(SPEAK_KEY, e.target.checked));
  if (!tts.ok) $("autoSpeak").parentElement.hidden = true;

  // ---------- dragon toggle ----------
  function paintDragonBtn(on) {
    const b = $("dragonBtn");
    b.setAttribute("aria-pressed", String(on));
    b.setAttribute("aria-label", on ? "Hide the dragon" : "Show the dragon");
    b.title = on ? "Hide the dragon" : "Show the dragon";
  }
  $("dragonBtn").addEventListener("click", () => { const w = window.buddy; if (w && w.setVisible) w.setVisible(!w.visible); });
  document.addEventListener("buddy:visibility", (e) => paintDragonBtn(e.detail));
  paintDragonBtn(!!(window.buddy && window.buddy.visible));
  if (buddy().off) $("dragonBtn").hidden = true;

  // ---------- theme ----------
  const darkMq = matchMedia("(prefers-color-scheme: light)");
  function currentTheme() { return document.documentElement.dataset.theme || (darkMq.matches ? "light" : "dark"); }
  function paintThemeBtn() {
    const next = currentTheme() === "dark" ? "light" : "dark";
    $("themeBtn").setAttribute("aria-label", `Switch to ${next} mode`);
    document.querySelector('meta[name="theme-color"]').content = currentTheme() === "dark" ? "#09090B" : "#FFFFFF";
  }
  $("themeBtn").addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    store.set(THEME_KEY, next);
    paintThemeBtn();
  });
  darkMq.addEventListener("change", paintThemeBtn);
  paintThemeBtn();

  // ---------- section nav: highlights the section on screen ----------
  const jumpLinks = [...document.querySelectorAll("#jump a")];
  if ("IntersectionObserver" in window) {
    const seen = new Map();
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) seen.set(e.target.id, e.isIntersecting ? e.intersectionRatio : 0);
      let best = "", bestR = 0;
      for (const [id, r] of seen) if (r > bestR) { best = id; bestR = r; }
      jumpLinks.forEach((a) => a.classList.toggle("on", a.getAttribute("href") === "#" + best));
    }, { threshold: [0, 0.2, 0.5, 0.8], rootMargin: "-110px 0px -40% 0px" });
    jumpLinks.forEach((a) => { const t = document.querySelector(a.getAttribute("href")); if (t) io.observe(t); });
  }

  // ---------- boot ----------
  updateCount();
  renderHistory();
  loadHealth();
})();
