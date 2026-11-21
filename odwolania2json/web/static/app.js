"use strict";

const state = { docs: [], current: null, types: [], filter: "", view: "list", llm: { enabled: false, mode: "fast" }, cases: [], casesFilter: "all", reviewDone: new Set() };
const $ = (sel) => document.querySelector(sel);
const ICON_DOC = '<svg viewBox="0 0 24 24"><path d="M7 3h7l5 5v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M14 3v5h5"/></svg>';
const ICON_TRASH = '<svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/></svg>';
const ICON_DL = '<svg viewBox="0 0 24 24"><path d="M12 4v12M7 11l5 5 5-5M4 20h16"/></svg>';
const ICON_OK = '<svg viewBox="0 0 24 24"><path d="m5 12 4 4 10-10"/></svg>';
const ICON_BAD = '<svg viewBox="0 0 24 24"><path d="M12 8v5M12 16v.01"/><path d="M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>';
const ICON_SPARK = '<svg viewBox="0 0 24 24"><path d="m12 3 1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z"/></svg>';
const TYPE_ORDER = ["odwolanie", "pelnomocnictwo", "przelew"];

/** Escape text for safe insertion into HTML. */
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** Polish plural form for counts. */
function plural(n, one, few, many) {
  if (n === 1) return one;
  const tens = n % 100;
  return n % 10 >= 2 && n % 10 <= 4 && (tens < 12 || tens > 14) ? few : many;
}

/** Show a short notification. */
function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.add("hidden"), 2800);
}

/** Call the backend and parse JSON, raising on HTTP errors. */
async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || response.statusText);
  return response.json();
}

/** POST or PUT JSON to the backend. */
function send(path, method, body) {
  return api(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

/** Run a slow action behind the loading overlay. */
async function busy(text, action) {
  $("#overlay-text").textContent = text;
  $("#overlay").classList.remove("hidden");
  try {
    return await action();
  } finally {
    $("#overlay").classList.add("hidden");
  }
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

/** Fields that deserve a human look: empty with context, ambiguous matches, or LLM disagreement. */
function reviewItems(doc) {
  if (!doc.doc_type) return [];
  const optional = new Set(state.types.find((t) => t.name === doc.doc_type)?.optional || []);
  return (doc.fields || []).filter((f) => {
    if (f.source === "manual") return false;
    if (f.llm_check === "rozbieżne" || f.llm_check === "uzupełnione") return true;
    if (f.ambiguous) return true;
    return !optional.has(f.field) && (f.value === null || f.value === "" || (Array.isArray(f.value) && !f.value.length)) && f.review_context;
  });
}

/** Main party name of a document for the overview table. */
function subject(doc) {
  return (doc.case_values?.party || [])[0] || "—";
}

/** Procurement reference of a document for the overview table. */
function procedure(doc) {
  if (doc.case_values?.reference) return doc.case_values.reference;
  const amount = doc.data?.przelew_bankowy?.kwota;
  return amount != null ? `${Number(amount).toFixed(2)} zł` : "—";
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
    if (!state.docs.length) return toast("Najpierw dodaj dokument");
    return openDoc(state.docs[0].id);
  }
  state.view = view;
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== `view-${view}`));
  $("#more-sheet").classList.add("hidden");
  const secondary = ["types", "settings", "help"].includes(view);
  $("#more-btn").classList.toggle("active", secondary);
  document.querySelectorAll(".rail-btn[data-go]").forEach((b) => {
    const active = b.dataset.go === view;
    b.classList.toggle("active", active);
    if (active) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  if (view === "assistant") $("#ask-input").focus();
  window.scrollTo({ top: 0 });
}

/** Update the KPI tiles. */
function renderKpis() {
  const docs = state.docs;
  const known = docs.filter((d) => d.doc_type);
  const fills = known.map(completeness).filter((v) => v !== null);
  const realCases = state.cases.filter((c) => c.reference);
  const incomplete = realCases.filter((c) => c.missing_types.length || !c.consistent).length;
  $("#k-cases").textContent = realCases.length;
  $("#k-cases-sub").innerHTML = realCases.length
    ? (incomplete ? `<span class="warn">${incomplete} ${plural(incomplete, "wymaga", "wymagają", "wymaga")} uwagi</span>` : "wszystkie kompletne i zgodne")
    : "po numerze postępowania";
  $("#k-total").textContent = docs.length;
  const unknown = docs.length - known.length;
  $("#k-total-sub").innerHTML = `rozpoznane: <b>${known.length}</b>${unknown ? ` · <span class="warn">spoza puli: ${unknown}</span>` : ""}`;
  $("#k-fill").textContent = fills.length ? `${Math.round((fills.reduce((a, b) => a + b, 0) / fills.length) * 100)}%` : "–";
  const toReview = known.reduce((n, d) => n + reviewItems(d).length, 0);
  $("#k-review-sub").innerHTML = toReview ? `do weryfikacji: <span class="warn">${toReview} ${plural(toReview, "pole", "pola", "pól")}</span>` : "do weryfikacji: 0 pól";
  $("#k-time").textContent = docs.length ? `${(docs.reduce((a, d) => a + d.seconds, 0) / docs.length).toFixed(2)} s` : "–";
  $("#k-ocr").textContent = `skany (OCR): ${docs.filter((d) => d.ocr).length}`;
}

/** Render the overview table. */
function renderTable() {
  const query = ($("#table-search").value || $("#search").value).trim().toLowerCase();
  const rows = state.docs.filter((d) => (!state.filter || d.doc_type === state.filter || (state.filter === "none" && !d.doc_type))
    && (!query || `${d.filename} ${subject(d)} ${procedure(d)} ${d.doc_label}`.toLowerCase().includes(query)));
  $("#rows").innerHTML = rows.map((d) => {
    const fill = completeness(d);
    const pct = fill === null ? null : Math.round(fill * 100);
    const review = reviewItems(d).length;
    return `<tr data-id="${d.id}" tabindex="0">
      <td class="cell-file"><div class="file-cell"><span class="file-icon ${d.doc_type || ""}">${ICON_DOC}</span>
        <div><div class="file-name">${esc(d.filename)}</div><div class="file-sub">${d.ocr ? "skan · OCR" : "PDF z tekstem"}${review ? ` · <span class="warn">${review} do weryfikacji</span>` : ""}</div></div></div></td>
      <td data-label="Typ"><span class="chip ${d.doc_type || "none"}">${esc(d.doc_label)}</span></td>
      <td data-label="Podmiot"><div class="cell-main" title="${esc(subject(d))}">${esc(subject(d))}</div></td>
      <td data-label="Postępowanie"><span class="mono">${esc(procedure(d))}</span></td>
      <td data-label="Kompletność">${pct === null ? '<span class="muted">—</span>' : `<div class="meter"><div class="meter-bar"><span class="${pct < 80 ? "mid" : ""}" style="width:${pct}%"></span></div><span class="meter-val">${pct}%</span></div>`}</td>
      <td class="muted cell-time" data-label="Czas">${d.seconds.toFixed(2)} s</td>
      <td class="cell-actions"><div class="row-actions">
        <a class="icon-btn" href="/api/documents/${d.id}/json" title="Pobierz JSON" aria-label="Pobierz JSON ${esc(d.filename)}" data-stop>${ICON_DL}</a>
        <button class="icon-btn danger" data-del="${d.id}" title="Usuń dokument" aria-label="Usuń ${esc(d.filename)}" data-stop>${ICON_TRASH}</button></div></td>
    </tr>`;
  }).join("");
  $("#empty-table").classList.toggle("hidden", state.docs.length > 0);
  $("#dropzone").classList.toggle("compact", state.docs.length > 0);
  $("#table-foot").textContent = state.docs.length ? `${rows.length} z ${state.docs.length} ${plural(state.docs.length, "dokumentu", "dokumentów", "dokumentów")}` : "";
  $("#table-foot").classList.toggle("hidden", !state.docs.length);
  renderKpis();
}

/** Tell whether a case needs attention (party mismatch, missing documents or no reference). */
function needsAttention(c) {
  return !c.reference || !c.consistent || c.missing_types.length > 0;
}

/** Fetch case groups from the server and render them. */
async function refreshCases() {
  state.cases = state.docs.length ? await api("/api/cases").catch(() => []) : [];
  renderCases();
}

/** Render the cases view and the navigation badge. */
function renderCases() {
  const attention = state.cases.filter(needsAttention).length;
  const badge = $("#cases-badge");
  badge.textContent = attention;
  badge.classList.toggle("hidden", !attention);
  const shown = state.casesFilter === "attention" ? state.cases.filter(needsAttention) : state.cases;
  $("#cases-empty").classList.toggle("hidden", shown.length > 0);
  $("#cases-empty").querySelector("b").textContent = state.cases.length ? "Wszystkie sprawy są kompletne i zgodne" : "Brak spraw";
  document.querySelectorAll("#cases-filter button").forEach((b) => {
    const on = b.dataset.cases === state.casesFilter;
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", String(on));
    if (b.dataset.cases === "attention") b.textContent = `Wymagające uwagi (${attention})`;
  });
  const labels = Object.fromEntries(state.types.map((t) => [t.name, t.label]));
  $("#cases").innerHTML = shown.map((c) => {
    const status = !c.reference
      ? '<span class="status warn">bez numeru postępowania</span>'
      : c.consistent
        ? `<span class="status ok">${ICON_OK}Zgodne strony</span>`
        : `<span class="status bad">${ICON_BAD}Rozbieżność stron</span>`;
    const missing = c.missing_types.length
      ? `<div class="case-missing">${ICON_BAD.replace("<svg", '<svg width="14" height="14"')} Brakuje: ${c.missing_types.map((t) => `<span class="chip none">${esc(labels[t] || t)}</span>`).join("")}</div>`
      : "";
    return `<article class="case ${c.consistent ? "" : "bad"}">
      <div class="case-head"><span class="case-ref">${esc(c.reference || "Dokumenty bez numeru")}</span>${status}</div>
      <ul class="case-docs">${c.documents.sort((a, b) => TYPE_ORDER.indexOf(a.doc_type) - TYPE_ORDER.indexOf(b.doc_type)).map((d) => `
        <li class="${d.status === "rozbieżne" ? "outlier" : ""}" data-open="${d.id}" tabindex="0" title="${d.status === "rozbieżne" ? "Strona różni się od pozostałych dokumentów sprawy" : ""}">
          <span class="chip ${d.doc_type}">${esc(d.doc_label)}</span><span class="fname">${esc(d.filename)}</span>
          <span class="party">${esc((d.party || []).join(", ") || "—")}</span></li>`).join("")}</ul>${missing}</article>`;
  }).join("");
  renderKpis();
}

/** Render the type filter buttons. */
function renderFilter() {
  const buttons = [["", "Wszystkie"], ...state.types.map((t) => [t.name, t.label]), ["none", "Spoza puli"]];
  $("#type-filter").innerHTML = buttons.map(([v, l]) => `<button class="${state.filter === v ? "active" : ""}" data-type="${esc(v)}" aria-pressed="${state.filter === v}">${esc(l)}</button>`).join("");
}

/** Replace a document in the local list and re-render dependent parts. */
function updateDoc(doc) {
  const i = state.docs.findIndex((d) => d.id === doc.id);
  if (i >= 0) state.docs[i] = doc;
  state.current = doc;
  renderTable();
}

/** Open the detail view of a document. */
async function openDoc(id) {
  const doc = await api(`/api/documents/${id}`);
  updateDoc(doc);
  $("#summary-card").classList.add("hidden");
  renderDetail(doc);
  go("detail");
}

/** Render every part of the detail view for the current document. */
function renderDetail(doc) {
  $("#d-title").textContent = doc.filename;
  $("#d-sub").textContent = doc.doc_type ? `Rozpoznano: ${doc.doc_label}` : "Nie udało się dopasować typu dokumentu";
  $("#d-open").href = `/api/documents/${doc.id}/pdf`;
  $("#d-dl").href = $("#btn-download").href = `/api/documents/${doc.id}/json`;
  $("#d-type").value = doc.doc_type || "";
  const fill = completeness(doc);
  const llmFields = doc.fields.filter((f) => f.llm_check).length;
  $("#d-facts").innerHTML = [
    ["Typ", `<span class="chip ${doc.doc_type || "none"}">${esc(doc.doc_label)}</span>`],
    ["Kompletność", fill === null ? "—" : `${Math.round(fill * 100)}%`],
    ["Czas analizy", `${doc.seconds.toFixed(2)} s`],
    ["Źródło tekstu", doc.ocr ? `OCR (${esc(doc.ocr.engine)})` : "Warstwa tekstowa"],
    ["Weryfikacja LLM", llmFields ? `${llmFields} ${plural(llmFields, "pole", "pola", "pól")}` : "Nie"],
    ["Klasyfikacja", `${doc.classification.score} pkt`],
  ].map(([l, v]) => `<div><div class="fact-label">${l}</div><div class="fact-value">${v}</div></div>`).join("");
  if (!$("#d-pdf iframe") || $("#d-pdf").dataset.id !== doc.id) {
    $("#d-pdf").dataset.id = doc.id;
    $("#d-pdf").innerHTML = `<iframe src="/api/documents/${doc.id}/pdf#view=FitH&navpanes=0&pagemode=none" title="Podgląd PDF ${esc(doc.filename)}"></iframe>`;
  }
  $("#d-json").innerHTML = doc.data && Object.keys(doc.data).length ? highlight(doc.data)
    : `<div class="empty-state"><b>Nie udało się dopasować typu dokumentu</b><span>${esc(doc.message || "")}</span><span>Wynikiem jest pusty JSON <code>{}</code>. Jeśli to pomyłka, wybierz typ z listy w nagłówku.</span></div>`;
  const review = reviewItems(doc);
  const count = review.filter((f) => !state.reviewDone.has(`${doc.id}:${f.field}`)).length;
  $("#review-count").textContent = count;
  $("#review-count").classList.toggle("zero", !count);
  $("#banner-text").innerHTML = count
    ? `<b>${count} ${plural(count, "pole wymaga", "pola wymagają", "pól wymaga")} weryfikacji.</b> Otwórz zakładkę Weryfikacja, sprawdź fragment dokumentu i popraw lub zatwierdź wartość.`
    : "Skąd pochodzi wartość? Otwórz zakładkę <b>Źródła</b> i kliknij pole.";
  renderReview(doc, review);
  renderSources(doc);
  renderText(doc);
  renderClassification(doc);
}

/** Short reason why a field is in the review queue. */
function reviewReason(f) {
  if (f.llm_check === "rozbieżne") return "LLM odczytał inną wartość niż reguły";
  if (f.llm_check === "uzupełnione") return "Uzupełnione przez LLM, potwierdź";
  if (f.ambiguous) return "W dokumencie jest kilka pasujących wartości";
  return "Reguły nie znalazły wartości";
}

/** Render the review queue with editable values. */
function renderReview(doc, items) {
  if (!items.length) {
    $("#d-review").innerHTML = '<div class="empty-state"><b>Nic do weryfikacji</b><span>Wszystkie pola mają jednoznaczne źródło w dokumencie.</span></div>';
    return;
  }
  $("#d-review").innerHTML = `<div class="review-list">${items.map((f) => {
    const done = state.reviewDone.has(`${doc.id}:${f.field}`);
    const complex = f.value !== null && typeof f.value === "object" || (f.llm_value !== null && typeof f.llm_value === "object");
    const shown = f.value === null || f.value === undefined ? "" : complex ? JSON.stringify(f.value, null, 1) : String(f.value);
    const llm = f.llm_value === null || f.llm_value === undefined ? null : complex ? JSON.stringify(f.llm_value) : String(f.llm_value);
    const input = complex
      ? `<textarea data-edit="${esc(f.field)}" aria-label="Wartość pola ${esc(f.field)}">${esc(shown)}</textarea>`
      : `<input data-edit="${esc(f.field)}" value="${esc(shown)}" placeholder="brak wartości" aria-label="Wartość pola ${esc(f.field)}">`;
    return `<div class="review-item ${done ? "done" : ""}">
      <div class="review-top"><span class="review-name">${esc(f.field)}</span><span class="status ${f.llm_check === "rozbieżne" ? "bad" : "warn"}">${esc(reviewReason(f))}</span></div>
      ${llm !== null ? `<div class="review-compare"><div><small>Reguły</small>${esc(shown || "brak")}</div><div><small>LLM</small>${esc(llm)}</div></div>` : ""}
      ${f.review_context || f.snippet ? `<div class="review-context">${esc(f.review_context || f.snippet)}</div>` : ""}
      <div class="review-edit">${input}
        <button class="btn primary" data-save="${esc(f.field)}">Zapisz</button>
        ${llm !== null ? `<button class="btn" data-use-llm="${esc(f.field)}">Użyj wartości LLM</button>` : ""}
        <button class="btn" data-accept="${esc(f.field)}">${shown ? "Zatwierdź" : "Zostaw puste"}</button>
      </div></div>`;
  }).join("")}</div>`;
}

/** Save a manually corrected field value. */
async function saveField(field, raw) {
  let value = raw;
  const trimmed = String(raw ?? "").trim();
  if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
    try {
      value = JSON.parse(trimmed);
    } catch {
      return toast("Niepoprawny JSON w polu");
    }
  } else if (trimmed === "") {
    value = null;
  }
  const doc = await send(`/api/documents/${state.current.id}/fields/${encodeURIComponent(field)}`, "PUT", { value });
  state.reviewDone.add(`${doc.id}:${field}`);
  updateDoc(doc);
  renderDetail(doc);
  refreshCases();
  toast(`Zapisano pole ${field}`);
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
    const flags = [
      f.source === "manual" ? '<span class="chip neutral">poprawione ręcznie</span>' : "",
      f.llm_check === "zgodne" ? '<span class="chip ok">LLM: zgodne</span>' : "",
      f.llm_check === "rozbieżne" ? '<span class="chip err">LLM: rozbieżne</span>' : "",
      f.ambiguous ? '<span class="chip none">niejednoznaczne</span>' : "",
    ].join("");
    return `<div class="src ${clickable ? "clickable" : ""}" data-field="${i}" ${clickable ? 'tabindex="0"' : ""}>
      <div class="src-top"><span class="src-name">${esc(f.field)}${flags}</span><span class="src-method">${esc(f.source)} · ${esc(f.method || "brak dopasowania")}</span></div>
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
    <div class="bar"><span style="width:${(Math.max(0, score) / max) * 100}%"></span></div><span>${score}</span>
    <div class="class-hits">${(doc.classification.matched[name] || []).map(esc).join(" · ") || "brak dopasowań"}</div></div>`).join("")
    || '<div class="empty-state">Brak danych</div>';
}

/** Activate a result tab. */
function showTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  ["json", "review", "fields", "text", "class"].forEach((t) => $(`#tab-${t}`).classList.toggle("hidden", t !== name));
}

/** Upload and process PDFs. */
async function upload(files) {
  const pdfs = [...files].filter((f) => f.name.toLowerCase().endsWith(".pdf"));
  if (!pdfs.length) return toast("Wybierz pliki PDF");
  const form = new FormData();
  pdfs.forEach((f) => form.append("files", f));
  try {
    const results = await busy(`Analizuję ${pdfs.length} ${plural(pdfs.length, "dokument", "dokumenty", "dokumentów")}…`, () => api("/api/documents", { method: "POST", body: form }));
    state.docs.push(...results);
    renderTable();
    await refreshCases();
    toast(`Przetworzono: ${results.length}`);
    if (results.length === 1) openDoc(results[0].id);
  } catch (e) {
    toast(`Błąd: ${e.message}`);
  } finally {
    $("#file").value = "";
  }
}

/** Download all recognized results. */
async function exportAll() {
  if (!state.docs.length) return toast("Brak wyników do pobrania");
  for (const d of state.docs) {
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
  if (!state.current) return toast("Brak JSON do skopiowania");
  await navigator.clipboard.writeText(JSON.stringify(state.current.data || {}, null, 2));
  toast("Skopiowano JSON");
}

/** Reflect LLM availability and mode in the header, settings and detail actions. */
function applyLlmState() {
  const { enabled, mode, model } = state.llm;
  const accurate = enabled && mode === "accurate";
  $("#mode-label").textContent = accurate ? "Tryb dokładny" : "Tryb szybki";
  const status = $("#llm-status");
  status.textContent = enabled ? `LLM: ${String(model).split("/").pop()}` : "LLM: wyłączony";
  status.className = enabled ? (accurate ? "accurate" : "on") : "";
  document.querySelectorAll(".llm-only").forEach((b) => {
    b.disabled = !enabled;
    b.title = enabled ? "" : "Włącz model językowy w Ustawieniach";
  });
  $("#assistant-off").classList.toggle("hidden", enabled);
  $("#ask-btn").disabled = !enabled;
  document.querySelectorAll("#mode-switch button").forEach((b) => {
    const on = b.dataset.mode === (mode || "fast");
    b.classList.toggle("active", on);
    b.setAttribute("aria-checked", String(on));
  });
}

/** Fill the LLM settings form from the server. */
async function loadLlm() {
  state.llm = await api("/api/llm");
  $("#llm-enabled").checked = state.llm.enabled;
  $("#llm-enabled-label").textContent = state.llm.enabled ? "Włączony" : "Wyłączony";
  $("#llm-url").value = state.llm.base_url;
  $("#llm-model").value = state.llm.model;
  $("#llm-key").value = "";
  $("#llm-key-hint").textContent = state.llm.has_key ? "Klucz jest ustawiony." : "Brak klucza (niepotrzebny dla lokalnej Ollamy).";
  applyLlmState();
}

/** Current LLM form values. */
function llmForm(extra = {}) {
  return { enabled: $("#llm-enabled").checked, base_url: $("#llm-url").value, model: $("#llm-model").value, api_key: $("#llm-key").value, ...extra };
}

/** Save LLM settings. */
async function saveLlm() {
  await send("/api/llm", "PUT", llmForm({ persist: $("#llm-persist").checked }));
  await loadLlm();
  toast("Zapisano ustawienia LLM");
}

/** Switch between fast and accurate mode. */
async function setMode(mode) {
  if (mode === "accurate" && !state.llm.enabled) {
    $("#llm-enabled").checked = true;
    $("#llm-enabled-label").textContent = "Włączony";
  }
  await send("/api/llm", "PUT", llmForm({ mode }));
  await loadLlm();
  toast(mode === "accurate" ? "Tryb dokładny: nowe dokumenty będą weryfikowane przez LLM" : "Tryb szybki: same reguły");
}

/** Test the LLM endpoint with the values currently in the form. */
async function testLlm() {
  const out = $("#llm-check-out");
  out.className = "muted";
  out.innerHTML = '<span class="spinner" style="display:inline-block;vertical-align:middle"></span> Testuję…';
  await send("/api/llm", "PUT", llmForm());
  const r = await api("/api/llm/check", { method: "POST" });
  out.className = r.ok ? "ok" : "err";
  out.textContent = r.ok ? `Działa: ${r.model}, odpowiedź w ${r.seconds} s.` : `Błąd: ${r.error}`;
  await loadLlm();
}

/** Re-run extraction of the current document with the LLM. */
async function refineWithLlm() {
  if (!state.current) return;
  try {
    const doc = await busy("Model sprawdza pola…", () => api(`/api/documents/${state.current.id}/reprocess?llm=true`, { method: "POST" }));
    updateDoc(doc);
    renderDetail(doc);
    refreshCases();
    const changed = doc.fields.filter((f) => f.llm_check && f.llm_check !== "zgodne").length;
    toast(changed ? `LLM: ${changed} ${plural(changed, "pole", "pola", "pól")} do weryfikacji` : "LLM potwierdził wartości");
    if (changed) showTab("review");
  } catch (e) {
    toast(`Błąd LLM: ${e.message}`);
  }
}

/** Ask the LLM for a summary of the current document. */
async function showSummary() {
  if (!state.current) return;
  try {
    const s = await busy("Przygotowuję streszczenie…", () => api(`/api/documents/${state.current.id}/summary`, { method: "POST" }));
    const list = (items) => items.length ? `<ul>${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>` : '<p class="muted">—</p>';
    $("#summary-card").innerHTML = `<h2>${ICON_SPARK}Streszczenie <span class="chip neutral">wygenerowane przez LLM</span></h2>
      <p>${esc(s.summary)}</p><div class="summary-cols"><div><b>Kluczowe punkty</b>${list(s.points)}</div><div><b>Terminy i kwoty</b>${list(s.facts)}</div></div>`;
    $("#summary-card").classList.remove("hidden");
  } catch (e) {
    toast(`Błąd LLM: ${e.message}`);
  }
}

/** Ask a question about all uploaded documents (retrieval-augmented). */
async function askQuestion(question) {
  question = question.trim();
  if (!question) return;
  if (!state.docs.length) return toast("Najpierw dodaj dokumenty");
  const box = document.createElement("div");
  box.className = "answer";
  box.innerHTML = `<div class="answer-q">${ICON_SPARK}${esc(question)}</div><div class="answer-a"><span class="spinner" style="display:inline-block"></span></div>`;
  $("#answers").prepend(box);
  $("#ask-input").value = "";
  try {
    const r = await send("/api/ask", "POST", { question });
    box.querySelector(".answer-a").textContent = r.answer || "Brak odpowiedzi.";
    box.insertAdjacentHTML("beforeend", `<div class="answer-sources">${r.sources.map((s) => `
      <button class="source" data-doc="${s.doc_id}" data-start="${s.start}" data-end="${s.end}">
        <span class="source-n">${s.n}</span><span><span class="source-file">${esc(s.filename)}</span><span class="source-snip">${esc(s.snippet.slice(0, 220))}…</span></span></button>`).join("")}</div>`);
  } catch (e) {
    box.querySelector(".answer-a").textContent = `Błąd: ${e.message}`;
  }
}

/** Format a byte count. */
function bytes(n) {
  return n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} kB`;
}

/** Open the update dialog with what a patch update would download. */
function openUpdate() {
  const u = state.update || {};
  const modal = $("#update-modal");
  const action = $("#update-action");
  $("#update-progress").classList.add("hidden");
  $("#update-progress-text").textContent = "";
  $("#update-notes").href = u.url || "#";
  $("#update-notes").classList.toggle("hidden", !u.url);
  if (!u.available) {
    $("#update-sub").textContent = `Wersja ${u.current || ""}`;
    $("#update-text").textContent = u.latest ? "Masz najnowszą wersję." : "Nie udało się sprawdzić aktualizacji (brak połączenia z GitHubem lub repozytorium nie jest publiczne).";
    action.classList.add("hidden");
  } else if (u.delta) {
    $("#update-sub").textContent = `${u.current} → ${u.latest}`;
    $("#update-text").textContent = u.delta.files
      ? `Zmieniło się ${u.delta.files} z ${u.delta.total_files} plików. Pobierzemy tylko je: ${bytes(u.delta.bytes)}. Twoja konfiguracja i foldery input/output zostaną bez zmian.`
      : "Pliki są już aktualne. Wystarczy ponowne uruchomienie.";
    action.textContent = "Aktualizuj";
    action.classList.remove("hidden");
    action.onclick = startUpdate;
  } else {
    $("#update-sub").textContent = `${u.current} → ${u.latest}`;
    $("#update-text").textContent = "Ta instancja działa ze źródeł lub w Dockerze. Pobierz nową wersję ze strony wydań albo zaktualizuj repozytorium (git pull).";
    action.textContent = "Otwórz stronę wydania";
    action.classList.remove("hidden");
    action.onclick = () => window.open(u.url, "_blank");
  }
  modal.querySelector(".form-foot").classList.toggle("hidden", action.classList.contains("hidden") && !u.url);
  modal.classList.remove("hidden");
}

/** Download the patch and follow its progress. */
async function startUpdate() {
  const action = $("#update-action");
  action.disabled = true;
  $("#update-progress").classList.remove("hidden");
  let s = await api("/api/update/start", { method: "POST" });
  while (s.stage === "downloading") {
    const pct = s.total ? Math.round((s.done / s.total) * 100) : 100;
    $("#update-bar").style.width = `${pct}%`;
    $("#update-progress-text").textContent = `${bytes(s.done || 0)} z ${bytes(s.total || 0)}`;
    await new Promise((r) => setTimeout(r, 500));
    s = await api("/api/update/status");
  }
  action.disabled = false;
  if (s.stage === "ready") {
    $("#update-bar").style.width = "100%";
    $("#update-progress-text").textContent = "Pobrano i zweryfikowano (SHA-256).";
    action.textContent = "Uruchom ponownie";
    action.onclick = async () => {
      await api("/api/update/restart", { method: "POST" });
      $("#update-text").textContent = "Aplikacja uruchamia się ponownie z nową wersją…";
      action.classList.add("hidden");
    };
  } else {
    $("#update-progress-text").textContent = `Błąd: ${s.error || "nieznany"}`;
  }
}

/** Load app info, document types and update status. */
async function loadInfo() {
  const info = await api("/api/info");
  state.types = info.types;
  $("#d-type").innerHTML = '<option value="">Typ: automatycznie</option>' + info.types.map((t) => `<option value="${esc(t.name)}">${esc(t.label)}</option>`).join("");
  $("#types").innerHTML = info.types.map((t) => `<div class="card type-card">
      <span class="chip ${esc(t.name)}">${esc(t.name)}</span><h3>${esc(t.label)}</h3>
      <div class="muted">Plik: <code>${esc(t.source)}</code></div>
      <div class="type-fields">${t.fields.map((f) => `<span class="chip neutral">${esc(f)}</span>`).join("")}</div></div>`).join("");
  renderFilter();
  api("/api/update").then((u) => {
    state.update = u;
    if (!u.available) return;
    $("#update-dot").classList.remove("hidden");
    $("#update-btn").title = `Dostępna wersja ${u.latest}`;
  }).catch(() => {});
}

/** Remove one document after confirmation. */
async function deleteDoc(id) {
  const doc = state.docs.find((d) => d.id === id);
  if (!doc || !window.confirm(`Usunąć dokument „${doc.filename}” z listy?`)) return;
  await api(`/api/documents/${id}`, { method: "DELETE" });
  state.docs = state.docs.filter((d) => d.id !== id);
  if (state.current?.id === id) state.current = null;
  renderTable();
  refreshCases();
}

/** Wire up event handlers. */
function bind() {
  document.addEventListener("click", (e) => {
    const target = e.target.closest("[data-go]");
    if (target) { e.preventDefault(); go(target.dataset.go); }
  });
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
  const openRow = (e) => {
    if (e.target.closest("[data-stop]")) return;
    const row = e.target.closest("tr[data-id]");
    if (row) openDoc(row.dataset.id);
  };
  $("#rows").addEventListener("click", (e) => {
    const del = e.target.closest("[data-del]");
    if (del) return deleteDoc(del.dataset.del);
    openRow(e);
  });
  $("#rows").addEventListener("keydown", (e) => { if (e.key === "Enter") openRow(e); });
  $("#cases").addEventListener("click", (e) => { const li = e.target.closest("[data-open]"); if (li) openDoc(li.dataset.open); });
  $("#cases-filter").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { state.casesFilter = b.dataset.cases; renderCases(); } });
  $("#cases").addEventListener("keydown", (e) => { const li = e.target.closest("[data-open]"); if (li && e.key === "Enter") openDoc(li.dataset.open); });
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
  $("#d-review").addEventListener("click", (e) => {
    const save = e.target.closest("[data-save]");
    const use = e.target.closest("[data-use-llm]");
    const accept = e.target.closest("[data-accept]");
    if (save) return saveField(save.dataset.save, $(`[data-edit="${CSS.escape(save.dataset.save)}"]`).value);
    if (use) {
      const f = state.current.fields.find((x) => x.field === use.dataset.useLlm);
      return saveField(f.field, typeof f.llm_value === "object" ? JSON.stringify(f.llm_value) : f.llm_value);
    }
    if (accept) {
      state.reviewDone.add(`${state.current.id}:${accept.dataset.accept}`);
      renderDetail(state.current);
    }
  });
  $("#review-banner").addEventListener("click", () => showTab(Number($("#review-count").textContent) ? "review" : "fields"));
  $("#d-type").addEventListener("change", async (e) => {
    if (!state.current) return;
    const q = e.target.value ? `?doc_type=${encodeURIComponent(e.target.value)}` : "";
    await api(`/api/documents/${state.current.id}/reprocess${q}`, { method: "POST" });
    await openDoc(state.current.id);
    refreshCases();
  });
  $("#btn-copy").addEventListener("click", copyJson);
  $("#d-copy").addEventListener("click", copyJson);
  $("#btn-llm").addEventListener("click", refineWithLlm);
  $("#btn-summary").addEventListener("click", showSummary);
  $("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); askQuestion($("#ask-input").value); });
  $("#ask-examples").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b && state.llm.enabled) askQuestion(b.textContent); });
  $("#answers").addEventListener("click", async (e) => {
    const s = e.target.closest(".source");
    if (!s) return;
    await openDoc(s.dataset.doc);
    showTab("text");
    renderText(state.current, [Number(s.dataset.start), Number(s.dataset.end)]);
  });
  $("#mode-switch").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setMode(b.dataset.mode); });
  $("#update-btn").addEventListener("click", openUpdate);
  $("#more-btn").addEventListener("click", () => {
    $("#more-sheet").classList.remove("hidden");
    $("#more-sheet .sheet-item").focus();
  });
  $("#more-sheet").addEventListener("click", (e) => { if (e.target.id === "more-sheet") $("#more-sheet").classList.add("hidden"); });
  $("#update-close").addEventListener("click", () => $("#update-modal").classList.add("hidden"));
  $("#update-modal").addEventListener("click", (e) => { if (e.target.id === "update-modal") $("#update-modal").classList.add("hidden"); });
  $("#llm-save").addEventListener("click", saveLlm);
  $("#llm-test").addEventListener("click", testLlm);
  $("#llm-enabled").addEventListener("change", (e) => { $("#llm-enabled-label").textContent = e.target.checked ? "Włączony" : "Wyłączony"; });
  $("#btn-upload").addEventListener("click", () => $("#file").click());
  $("#dropzone").addEventListener("click", (e) => { e.preventDefault(); $("#file").click(); });
  $("#dropzone").addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#file").click(); } });
  $("#file").addEventListener("change", (e) => upload(e.target.files));
  $("#btn-export").addEventListener("click", exportAll);
  $("#btn-clear").addEventListener("click", async () => {
    if (!state.docs.length || !window.confirm(`Usunąć wszystkie dokumenty (${state.docs.length}) z listy?`)) return;
    await Promise.all(state.docs.map((d) => api(`/api/documents/${d.id}`, { method: "DELETE" })));
    state.docs = [];
    state.current = null;
    renderTable();
    refreshCases();
  });
  $("#btn-reload").addEventListener("click", async () => {
    await api("/api/reload", { method: "POST" });
    await loadInfo();
    toast("Konfiguracja przeładowana");
  });
  $("#search").addEventListener("input", () => { if (state.view !== "list") go("list"); renderTable(); });
  $("#table-search").addEventListener("input", renderTable);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { $("#update-modal").classList.add("hidden"); $("#more-sheet").classList.add("hidden"); }
    if (e.key === "/" && !["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) {
      e.preventDefault();
      $("#search").focus();
    }
  });
  const dz = $("#dropzone");
  $("#dropzone").setAttribute("tabindex", "0");
  let depth = 0;
  document.addEventListener("dragenter", (e) => { e.preventDefault(); depth += 1; dz.classList.add("over"); if (state.view !== "list") go("list"); });
  document.addEventListener("dragover", (e) => e.preventDefault());
  document.addEventListener("dragleave", (e) => { e.preventDefault(); depth = Math.max(0, depth - 1); if (!depth) dz.classList.remove("over"); });
  document.addEventListener("drop", (e) => { e.preventDefault(); depth = 0; dz.classList.remove("over"); upload(e.dataTransfer.files); });
}

bind();
loadInfo().then(loadLlm).then(() => api("/api/documents")).then(async (docs) => { state.docs = docs || []; renderTable(); await refreshCases(); });
