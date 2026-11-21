"use strict";

const state = { docs: [], current: null, types: [] };
const $ = (sel) => document.querySelector(sel);
const DOC_ICON = '<svg viewBox="0 0 24 24"><path d="M7 3h7l5 5v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M14 3v5h5"/></svg>';
const TRASH = '<svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg>';

/** Escape text for safe insertion into HTML. */
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** Show a short notification in the corner. */
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

/** Render JSON with simple syntax highlighting. */
function highlight(data) {
  const json = JSON.stringify(data, null, 2);
  return esc(json).replace(/(&quot;(?:\\.|[^&]|&(?!quot;))*?&quot;)(\s*:)?|\b(true|false)\b|\bnull\b|-?\d+(?:\.\d+)?(?:e[+-]?\d+)?/g, (m, str, colon, bool) => {
    if (str) return colon ? `<span class="k">${str}</span>${colon}` : `<span class="s">${str}</span>`;
    if (bool) return `<span class="b">${m}</span>`;
    if (m === "null") return `<span class="z">null</span>`;
    return `<span class="n">${m}</span>`;
  });
}

/** Recompute the statistic tiles. */
function renderStats() {
  const count = (t) => state.docs.filter((d) => d.doc_type === t).length;
  $("#st-total").textContent = state.docs.length;
  $("#st-odwolanie").textContent = count("odwolanie");
  $("#st-pelnomocnictwo").textContent = count("pelnomocnictwo");
  $("#st-przelew").textContent = count("przelew");
  const avg = state.docs.length ? state.docs.reduce((s, d) => s + d.seconds, 0) / state.docs.length : null;
  $("#st-time").textContent = avg === null ? "–" : `${avg.toFixed(2)} s`;
  $("#doc-count").textContent = state.docs.length;
}

/** Render the list of uploaded documents, filtered by the search box. */
function renderList() {
  const query = $("#search").value.trim().toLowerCase();
  const list = $("#doc-list");
  const docs = state.docs.filter((d) => !query || d.filename.toLowerCase().includes(query) || (d.doc_label || "").toLowerCase().includes(query));
  list.innerHTML = docs.map((d) => `
    <li class="doc ${state.current?.id === d.id ? "active" : ""}" data-id="${d.id}">
      <span class="doc-icon ${d.doc_type || ""}">${DOC_ICON}</span>
      <span class="doc-body">
        <span class="doc-name" title="${esc(d.filename)}">${esc(d.filename)}</span>
        <span class="doc-sub"><span class="tag ${d.doc_type || "none"}">${esc(d.doc_label)}</span>${d.ocr ? ' <span class="tag ocr">OCR</span>' : ""}</span>
      </span>
      <button class="icon-btn doc-del" data-del="${d.id}" title="Usuń">${TRASH}</button>
    </li>`).join("") || '<li class="empty">Brak dokumentów</li>';
  renderStats();
}

/** Show one document: PDF preview, JSON, fields, text and classification. */
async function select(id) {
  const doc = await api(`/api/documents/${id}`);
  state.current = doc;
  const i = state.docs.findIndex((d) => d.id === id);
  if (i >= 0) state.docs[i] = doc;
  renderList();
  $("#preview-title").textContent = doc.filename;
  $("#pdf-frame").innerHTML = `<iframe src="/api/documents/${id}/pdf#view=FitH&navpanes=0&pagemode=none" title="Podgląd PDF"></iframe>`;
  $("#open-pdf").href = `/api/documents/${id}/pdf`;
  $("#dl-json").href = `/api/documents/${id}/json`;
  $("#type-select").value = doc.doc_type || "";
  const ocr = doc.ocr ? `<span class="tag ocr">OCR: ${esc(doc.ocr.engine)}, str. ${doc.ocr.pages.join(", ")}</span>` : "";
  const llm = doc.fields.some((f) => f.source === "llm") ? '<span class="tag ocr">uzupełnione przez LLM</span>' : "";
  $("#meta").innerHTML = `<span class="tag ${doc.doc_type || "none"}">${esc(doc.doc_label)}</span>
    <span class="tag ocr">${doc.seconds.toFixed(2)} s</span>${ocr}${llm}${doc.error ? `<span class="tag none">${esc(doc.error)}</span>` : ""}`;
  $("#json-out").innerHTML = doc.data ? highlight(doc.data) : '<span class="muted">Nie rozpoznano typu dokumentu — wybierz typ z listy powyżej, aby wymusić ekstrakcję.</span>';
  renderFields(doc);
  renderText(doc);
  renderClassification(doc);
}

/** Render the per-field provenance table. */
function renderFields(doc) {
  const rows = doc.fields.map((f, i) => {
    const value = typeof f.value === "object" && f.value !== null ? JSON.stringify(f.value) : f.value;
    const clickable = f.start !== null && f.start !== undefined;
    return `<tr class="${clickable ? "clickable" : ""}" data-field="${i}">
      <td><b>${esc(f.field)}</b><div class="src">${esc(f.source)} · ${esc(f.method || "brak")}</div></td>
      <td><div class="val">${value === null || value === undefined ? '<span class="muted">null</span>' : esc(value)}</div>
      ${f.snippet ? `<div class="snip">…${esc(f.snippet)}…</div>` : ""}</td></tr>`;
  }).join("");
  $("#fields-out").innerHTML = `<thead><tr><th>Pole</th><th>Wartość i źródło</th></tr></thead><tbody>${rows}</tbody>`;
}

/** Render extracted document text, optionally highlighting a span. */
function renderText(doc, span) {
  const text = doc.text || "";
  if (!span) {
    $("#text-out").textContent = text || "(brak tekstu)";
    return;
  }
  const [a, b] = span;
  $("#text-out").innerHTML = `${esc(text.slice(0, a))}<mark id="hit">${esc(text.slice(a, b))}</mark>${esc(text.slice(b))}`;
  document.getElementById("hit")?.scrollIntoView({ block: "center" });
}

/** Render classification scores and matched keywords. */
function renderClassification(doc) {
  const scores = doc.classification.scores || {};
  const max = Math.max(1, ...Object.values(scores));
  $("#class-out").innerHTML = Object.entries(scores).sort((a, b) => b[1] - a[1]).map(([name, score]) => `
    <div class="class-row"><b>${esc(name)}</b><div class="bar"><span style="width:${(score / max) * 100}%"></span></div><span>${score}</span>
    <div class="class-hits">${(doc.classification.matched[name] || []).map(esc).join(" · ") || "brak dopasowań"}</div></div>`).join("");
}

/** Switch the active result tab. */
function showTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  ["json", "fields", "text", "class"].forEach((t) => $(`#tab-${t}`).classList.toggle("hidden", t !== name));
}

/** Upload files and process them on the server. */
async function upload(files) {
  const pdfs = [...files].filter((f) => f.name.toLowerCase().endsWith(".pdf"));
  if (!pdfs.length) return toast("Wybierz pliki PDF");
  const form = new FormData();
  pdfs.forEach((f) => form.append("files", f));
  $("#drop").innerHTML = '<span class="spinner"></span><span>Przetwarzanie…</span>';
  try {
    const results = await api("/api/documents", { method: "POST", body: form });
    state.docs.push(...results);
    renderList();
    if (results.length) await select(results[results.length - 1].id);
    toast(`Przetworzono: ${results.length}`);
  } catch (e) {
    toast(`Błąd: ${e.message}`);
  } finally {
    resetDrop();
  }
}

/** Restore the drop zone content. */
function resetDrop() {
  $("#drop").innerHTML = '<input type="file" id="file" accept="application/pdf" multiple hidden><svg viewBox="0 0 24 24"><path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/></svg><span><b>Wgraj PDF</b> albo upuść pliki tutaj</span>';
  $("#file").addEventListener("change", (e) => upload(e.target.files));
}

/** Download every recognized JSON as separate files. */
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

/** Load app info and configured document types. */
async function loadInfo() {
  const info = await api("/api/info");
  state.types = info.types;
  $("#version").textContent = `v${info.version}`;
  const pill = $("#llm-pill");
  pill.textContent = info.llm ? `LLM: ${info.llm_model}` : "LLM: wyłączony";
  pill.classList.toggle("on", info.llm);
  $("#type-select").innerHTML = '<option value="">Typ: auto</option>' + info.types.map((t) => `<option value="${esc(t.name)}">${esc(t.label)}</option>`).join("");
  $("#types-out").innerHTML = info.types.map((t) => `
    <div class="card type-card"><h3>${esc(t.label)}</h3><span class="muted"><code>${esc(t.source)}</code></span>
    <ul>${t.fields.map((f) => `<li>${esc(f)}</li>`).join("")}</ul></div>`).join("");
}

/** Wire up all event handlers. */
function bind() {
  document.querySelectorAll(".rail-btn").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".rail-btn").forEach((x) => x.classList.toggle("active", x === b));
    document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== `view-${b.dataset.view}`));
  }));
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
  $("#doc-list").addEventListener("click", async (e) => {
    const del = e.target.closest("[data-del]");
    if (del) {
      e.stopPropagation();
      await api(`/api/documents/${del.dataset.del}`, { method: "DELETE" });
      state.docs = state.docs.filter((d) => d.id !== del.dataset.del);
      if (state.current?.id === del.dataset.del) state.current = null;
      return renderList();
    }
    const item = e.target.closest(".doc");
    if (item) select(item.dataset.id);
  });
  $("#fields-out").addEventListener("click", (e) => {
    const row = e.target.closest("tr.clickable");
    if (!row || !state.current) return;
    const f = state.current.fields[Number(row.dataset.field)];
    showTab("text");
    renderText(state.current, [f.start, f.end]);
  });
  $("#type-select").addEventListener("change", async (e) => {
    if (!state.current) return;
    const q = e.target.value ? `?doc_type=${encodeURIComponent(e.target.value)}` : "";
    await api(`/api/documents/${state.current.id}/reprocess${q}`, { method: "POST" });
    select(state.current.id);
  });
  $("#copy-json").addEventListener("click", async () => {
    if (!state.current?.data) return;
    await navigator.clipboard.writeText(JSON.stringify(state.current.data, null, 2));
    toast("Skopiowano JSON");
  });
  $("#btn-add").addEventListener("click", () => $("#file").click());
  $("#btn-export").addEventListener("click", exportAll);
  $("#btn-clear").addEventListener("click", async () => {
    await Promise.all(state.docs.map((d) => api(`/api/documents/${d.id}`, { method: "DELETE" })));
    state.docs = [];
    state.current = null;
    renderList();
    $("#pdf-frame").innerHTML = '<div class="empty">Wybierz dokument z listy</div>';
    $("#json-out").innerHTML = '<span class="muted">{ }</span>';
    $("#fields-out").innerHTML = "";
    $("#meta").innerHTML = "";
  });
  $("#btn-reload").addEventListener("click", async () => {
    await api("/api/reload", { method: "POST" });
    await loadInfo();
    toast("Konfiguracja przeładowana");
  });
  $("#search").addEventListener("input", renderList);
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && document.activeElement.tagName !== "INPUT") {
      e.preventDefault();
      $("#search").focus();
    }
  });
  const drop = $("#drop");
  ["dragenter", "dragover"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  document.addEventListener("drop", (e) => upload(e.dataTransfer.files));
  $("#file").addEventListener("change", (e) => upload(e.target.files));
}

bind();
loadInfo();
api("/api/documents").then((docs) => { state.docs = docs; renderList(); });
