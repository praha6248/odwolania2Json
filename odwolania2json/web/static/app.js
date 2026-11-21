"use strict";

const state = { docs: [], current: null, types: [], filter: "", view: "list" };
const $ = (sel) => document.querySelector(sel);
const ICON_DOC = '<svg viewBox="0 0 24 24"><path d="M7 3h7l5 5v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M14 3v5h5"/></svg>';
const ICON_TRASH = '<svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg>';
const ICON_DL = '<svg viewBox="0 0 24 24"><path d="M12 4v12M7 11l5 5 5-5M4 20h16"/></svg>';

/** Escape text for safe insertion into HTML. */
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** Show a short notification. */
function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.add("hidden"), 2600);
}

/** Call the backend and parse JSON, raising on HTTP errors. */
async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || response.statusText);
  return response.json();
}

/** Collect leaf values of nested data. */
function leaves(data, out = []) {
  if (Array.isArray(data)) data.forEach((v) => leaves(v, out));
  else if (data && typeof data === "object") Object.values(data).forEach((v) => leaves(v, out));
  else out.push(data);
  return out;
}

/** Share of non-null leaf values. */
function completeness(doc) {
  if (!doc.data) return null;
  const all = leaves(doc.data);
  return all.length ? all.filter((v) => v !== null && v !== "").length / all.length : 0;
}

/** Pick the main party name of a document for the overview table. */
function subject(doc) {
  const d = doc.data || {};
  return d.Odwolujacy?.[0]?.nazwa || d.mocodawca?.[0]?.data?.nazwa || d.przelew_bankowy?.tytul || "—";
}

/** Pick the procurement reference of a document for the overview table. */
function procedure(doc) {
  const d = doc.data || {};
  if (d.ZamowieniePubliczne?.numer_postepowania) return d.ZamowieniePubliczne.numer_postepowania;
  const title = d.przelew_bankowy?.tytul || "";
  const match = title.match(/przetargu\s+(\S+)/i);
  if (match) return match[1];
  if (d.przelew_bankowy?.kwota != null) return `${d.przelew_bankowy.kwota.toFixed(2)} zł`;
  return "—";
}

/** Render JSON with syntax highlighting. */
function highlight(data) {
  return esc(JSON.stringify(data, null, 2)).replace(/(&quot;(?:\\.|[^&]|&(?!quot;))*?&quot;)(\s*:)?|\b(true|false)\b|\bnull\b|-?\d+(?:\.\d+)?/g, (m, str, colon, bool) => {
    if (str) return colon ? `<span class="k">${str}</span>${colon}` : `<span class="s">${str}</span>`;
    if (bool) return `<span class="b">${m}</span>`;
    if (m === "null") return '<span class="z">null</span>';
    return `<span class="n">${m}</span>`;
  });
}

/** Switch between views. */
function go(view) {
  if (view === "detail" && !state.current) {
    if (!state.docs.length) return toast("Najpierw wgraj dokument");
    return openDoc(state.docs[0].id);
  }
  state.view = view;
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== `view-${view}`));
  document.querySelectorAll(".rail-btn").forEach((b) => b.classList.toggle("active", b.dataset.go === view));
  window.scrollTo({ top: 0 });
}

/** Update the KPI tiles. */
function renderKpis() {
  const docs = state.docs;
  const known = docs.filter((d) => d.doc_type);
  const fills = known.map(completeness).filter((v) => v !== null);
  $("#k-total").textContent = docs.length;
  $("#k-cases").textContent = `${docs.filter((d) => d.doc_type === "odwolanie").length} spraw`;
  $("#k-known").textContent = known.length;
  $("#k-known-pct").textContent = docs.length ? `${Math.round((known.length / docs.length) * 100)}%` : "–";
  $("#k-fill").textContent = fills.length ? `${Math.round((fills.reduce((a, b) => a + b, 0) / fills.length) * 100)}%` : "–";
  $("#k-time").textContent = docs.length ? `${(docs.reduce((a, d) => a + d.seconds, 0) / docs.length).toFixed(2)} s` : "–";
  $("#k-ocr").textContent = `${docs.filter((d) => d.ocr).length} OCR`;
}

/** Render the overview table. */
function renderTable() {
  const query = ($("#table-search").value || $("#search").value).trim().toLowerCase();
  const rows = state.docs.filter((d) => (!state.filter || d.doc_type === state.filter || (state.filter === "none" && !d.doc_type))
    && (!query || `${d.filename} ${subject(d)} ${procedure(d)} ${d.doc_label}`.toLowerCase().includes(query)));
  $("#rows").innerHTML = rows.map((d) => {
    const fill = completeness(d);
    const pct = fill === null ? null : Math.round(fill * 100);
    return `<tr data-id="${d.id}">
      <td><div class="file-cell"><span class="file-icon ${d.doc_type || ""}">${ICON_DOC}</span>
        <div><div class="file-name">${esc(d.filename)}</div><div class="file-sub">${d.ocr ? "skan · OCR" : "PDF z tekstem"}</div></div></div></td>
      <td><span class="chip ${d.doc_type || "none"}">${esc(d.doc_label)}</span></td>
      <td><div class="cell-main" title="${esc(subject(d))}">${esc(subject(d))}</div></td>
      <td><span class="mono">${esc(procedure(d))}</span></td>
      <td>${pct === null ? '<span class="muted">—</span>' : `<div class="meter"><div class="meter-bar"><span class="${pct < 80 ? "mid" : ""}" style="width:${pct}%"></span></div><span class="meter-val">${pct}%</span></div>`}</td>
      <td class="muted">${d.seconds.toFixed(2)} s</td>
      <td><div class="row-actions">
        ${d.doc_type ? `<a class="icon-btn" href="/api/documents/${d.id}/json" title="Pobierz JSON" data-stop>${ICON_DL}</a>` : ""}
        <button class="icon-btn" data-del="${d.id}" title="Usuń" data-stop>${ICON_TRASH}</button></div></td>
    </tr>`;
  }).join("");
  const dz = $("#dropzone");
  dz.classList.toggle("compact", state.docs.length > 0);
  $("#table-foot").textContent = state.docs.length ? `${rows.length} z ${state.docs.length} dokumentów` : "";
  $("#table-foot").classList.toggle("hidden", !state.docs.length);
  renderKpis();
}

/** Render the type filter buttons. */
function renderFilter() {
  const buttons = [["", "Wszystkie"], ...state.types.map((t) => [t.name, t.label]), ["none", "Nierozpoznane"]];
  $("#type-filter").innerHTML = buttons.map(([v, l]) => `<button class="${state.filter === v ? "active" : ""}" data-type="${esc(v)}">${esc(l)}</button>`).join("");
}

/** Open the detail view of a document. */
async function openDoc(id) {
  const doc = await api(`/api/documents/${id}`);
  state.current = doc;
  const i = state.docs.findIndex((d) => d.id === id);
  if (i >= 0) state.docs[i] = doc;
  $("#d-title").textContent = doc.filename;
  $("#d-sub").textContent = doc.doc_type ? `Rozpoznano: ${doc.doc_label}` : "Nie rozpoznano typu dokumentu";
  $("#d-open").href = `/api/documents/${id}/pdf`;
  $("#d-dl").href = $("#btn-download").href = `/api/documents/${id}/json`;
  $("#d-type").value = doc.doc_type || "";
  const fill = completeness(doc);
  const llm = doc.fields.some((f) => f.source === "llm");
  $("#d-facts").innerHTML = [
    ["Typ", `<span class="chip ${doc.doc_type || "none"}">${esc(doc.doc_label)}</span>`],
    ["Kompletność", fill === null ? "—" : `${Math.round(fill * 100)}%`],
    ["Czas analizy", `${doc.seconds.toFixed(2)} s`],
    ["Źródło tekstu", doc.ocr ? `OCR (${esc(doc.ocr.engine)})` : "Warstwa tekstowa"],
    ["Wsparcie LLM", llm ? "Tak" : "Nie"],
    ["Klasyfikacja", `${doc.classification.score} pkt`],
  ].map(([l, v]) => `<div><div class="fact-label">${l}</div><div class="fact-value">${v}</div></div>`).join("");
  $("#d-pdf").innerHTML = `<iframe src="/api/documents/${id}/pdf#view=FitH&navpanes=0&pagemode=none" title="Podgląd PDF"></iframe>`;
  $("#d-json").innerHTML = doc.data ? highlight(doc.data)
    : `<div class="empty-state"><b>Nie udało się dopasować typu dokumentu</b><span>${esc(doc.message || "")}</span><span>Jeśli to pomyłka, wybierz typ z listy w nagłówku, aby wymusić ekstrakcję.</span></div>`;
  renderSources(doc);
  renderText(doc);
  renderClassification(doc);
  go("detail");
}

/** Render per-field provenance cards. */
function renderSources(doc) {
  if (!doc.fields.length) {
    $("#d-fields").innerHTML = '<div class="empty-state"><b>Brak pól</b><span>Dokument nie został przetworzony żadnym typem.</span></div>';
    return;
  }
  $("#d-fields").innerHTML = `<div class="src-list">${doc.fields.map((f, i) => {
    const value = f.value !== null && typeof f.value === "object" ? JSON.stringify(f.value) : f.value;
    const clickable = f.start !== null && f.start !== undefined;
    return `<div class="src ${clickable ? "clickable" : ""}" data-field="${i}">
      <div class="src-top"><span class="src-name">${esc(f.field)}</span><span class="src-method">${esc(f.source)} · ${esc(f.method || "brak dopasowania")}</span></div>
      <div class="src-value">${value === null || value === undefined ? '<span class="muted">null</span>' : esc(value)}</div>
      ${f.snippet ? `<div class="src-snip">„…${esc(f.snippet)}…”</div>` : ""}</div>`;
  }).join("")}</div>`;
}

/** Render document text, optionally highlighting a span. */
function renderText(doc, span) {
  const text = doc.text || "";
  if (!span) {
    $("#d-text").textContent = text || "(brak tekstu)";
    return;
  }
  const [a, b] = span;
  $("#d-text").innerHTML = `${esc(text.slice(0, a))}<mark id="hit">${esc(text.slice(a, b))}</mark>${esc(text.slice(b))}`;
  document.getElementById("hit")?.scrollIntoView({ block: "center" });
}

/** Render classification scores. */
function renderClassification(doc) {
  const scores = doc.classification.scores || {};
  const max = Math.max(1, ...Object.values(scores));
  $("#d-class").innerHTML = Object.entries(scores).sort((a, b) => b[1] - a[1]).map(([name, score]) => `
    <div class="class-row"><b>${esc(state.types.find((t) => t.name === name)?.label || name)}</b>
    <div class="bar"><span style="width:${(score / max) * 100}%"></span></div><span>${score}</span>
    <div class="class-hits">${(doc.classification.matched[name] || []).map(esc).join(" · ") || "brak dopasowań"}</div></div>`).join("")
    || '<div class="empty-state">Brak danych</div>';
}

/** Activate a result tab. */
function showTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  ["json", "fields", "text", "class"].forEach((t) => $(`#tab-${t}`).classList.toggle("hidden", t !== name));
}

/** Upload and process PDFs. */
async function upload(files) {
  const pdfs = [...files].filter((f) => f.name.toLowerCase().endsWith(".pdf"));
  if (!pdfs.length) return toast("Wybierz pliki PDF");
  const form = new FormData();
  pdfs.forEach((f) => form.append("files", f));
  $("#overlay-text").textContent = `Analizuję ${pdfs.length} ${pdfs.length === 1 ? "dokument" : "dokumenty"}…`;
  $("#overlay").classList.remove("hidden");
  try {
    const results = await api("/api/documents", { method: "POST", body: form });
    state.docs.push(...results);
    renderTable();
    toast(`Przetworzono: ${results.length}`);
    if (results.length === 1) openDoc(results[0].id);
  } catch (e) {
    toast(`Błąd: ${e.message}`);
  } finally {
    $("#overlay").classList.add("hidden");
    $("#file").value = "";
  }
}

/** Download all recognized results. */
async function exportAll() {
  const ready = state.docs.filter((d) => d.doc_type);
  if (!ready.length) return toast("Brak wyników do pobrania");
  for (const d of ready) {
    const a = document.createElement("a");
    a.href = `/api/documents/${d.id}/json`;
    a.download = d.filename.replace(/\.pdf$/i, ".json");
    document.body.appendChild(a);
    a.click();
    a.remove();
    await new Promise((r) => setTimeout(r, 150));
  }
}

/** Copy the current JSON to the clipboard. */
async function copyJson() {
  if (!state.current?.data) return toast("Brak JSON do skopiowania");
  await navigator.clipboard.writeText(JSON.stringify(state.current.data, null, 2));
  toast("Skopiowano JSON");
}

/** Load app info, document types and update status. */
async function loadInfo() {
  const info = await api("/api/info");
  state.types = info.types;
  const llm = $("#llm-status");
  llm.textContent = info.llm ? `LLM: ${info.llm_model}` : `LLM: wyłączony · v${info.version}`;
  llm.classList.toggle("on", info.llm);
  $("#d-type").innerHTML = '<option value="">Typ: automatycznie</option>' + info.types.map((t) => `<option value="${esc(t.name)}">${esc(t.label)}</option>`).join("");
  $("#types").innerHTML = info.types.map((t) => `<div class="card type-card">
      <span class="chip ${esc(t.name)}">${esc(t.name)}</span><h3>${esc(t.label)}</h3>
      <div class="muted">Plik: <code>${esc(t.source)}</code></div>
      <div class="type-fields">${t.fields.map((f) => `<span class="chip neutral">${esc(f)}</span>`).join("")}</div></div>`).join("");
  renderFilter();
  api("/api/update").then((u) => {
    if (!u.available) return;
    $("#update-dot").classList.remove("hidden");
    $("#update-btn").title = `Dostępna wersja ${u.latest}`;
    $("#update-btn").onclick = () => window.open(u.url, "_blank");
  }).catch(() => {});
}

/** Wire up event handlers. */
function bind() {
  document.addEventListener("click", (e) => {
    const target = e.target.closest("[data-go]");
    if (target) { e.preventDefault(); go(target.dataset.go); }
  });
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
  $("#rows").addEventListener("click", async (e) => {
    const del = e.target.closest("[data-del]");
    if (del) {
      await api(`/api/documents/${del.dataset.del}`, { method: "DELETE" });
      state.docs = state.docs.filter((d) => d.id !== del.dataset.del);
      if (state.current?.id === del.dataset.del) state.current = null;
      return renderTable();
    }
    if (e.target.closest("[data-stop]")) return;
    const row = e.target.closest("tr[data-id]");
    if (row) openDoc(row.dataset.id);
  });
  $("#type-filter").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    state.filter = b.dataset.type;
    renderFilter();
    renderTable();
  });
  $("#d-fields").addEventListener("click", (e) => {
    const card = e.target.closest(".src.clickable");
    if (!card || !state.current) return;
    const f = state.current.fields[Number(card.dataset.field)];
    showTab("text");
    renderText(state.current, [f.start, f.end]);
  });
  $("#d-type").addEventListener("change", async (e) => {
    if (!state.current) return;
    const q = e.target.value ? `?doc_type=${encodeURIComponent(e.target.value)}` : "";
    await api(`/api/documents/${state.current.id}/reprocess${q}`, { method: "POST" });
    await openDoc(state.current.id);
    renderTable();
  });
  $("#btn-copy").addEventListener("click", copyJson);
  $("#d-copy").addEventListener("click", copyJson);
  $("#btn-upload").addEventListener("click", () => $("#file").click());
  $("#dropzone").addEventListener("click", (e) => { e.preventDefault(); $("#file").click(); });
  $("#file").addEventListener("change", (e) => upload(e.target.files));
  $("#btn-export").addEventListener("click", exportAll);
  $("#btn-clear").addEventListener("click", async () => {
    await Promise.all(state.docs.map((d) => api(`/api/documents/${d.id}`, { method: "DELETE" })));
    state.docs = [];
    state.current = null;
    renderTable();
  });
  $("#btn-reload").addEventListener("click", async () => {
    await api("/api/reload", { method: "POST" });
    await loadInfo();
    toast("Konfiguracja przeładowana");
  });
  $("#search").addEventListener("input", () => { if (state.view !== "list") go("list"); renderTable(); });
  $("#table-search").addEventListener("input", renderTable);
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) {
      e.preventDefault();
      $("#search").focus();
    }
  });
  const dz = $("#dropzone");
  ["dragenter", "dragover"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); if (ev === "drop" || !e.relatedTarget) dz.classList.remove("over"); }));
  document.addEventListener("drop", (e) => { if (state.view !== "list") go("list"); upload(e.dataTransfer.files); });
}

bind();
loadInfo().then(() => api("/api/documents")).then((docs) => { state.docs = docs || []; renderTable(); });
