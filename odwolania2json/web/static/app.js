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

const ROUTES = { list: "dokumenty", cases: "sprawy", detail: "dokument", assistant: "asystent", types: "typy", wizard: "nowy-typ", settings: "ustawienia", help: "pomoc" };
const TABS = { json: "json", review: "weryfikacja", fields: "zrodla", text: "tekst", class: "klasyfikacja" };

/** Write the current view (and document tab) into the URL hash without adding history noise. */
function setHash(view, tab) {
  const hash = view === "detail" && state.current ? `#/dokument/${state.current.id}/${TABS[tab || state.tab || "json"]}` : `#/${ROUTES[view] || "dokumenty"}`;
  if (location.hash !== hash) history.replaceState(null, "", hash);
}

/** Open the view described by the URL hash (deep links survive reloads). */
async function applyRoute() {
  const [, name, id, tab] = (location.hash || "").split("/");
  const view = Object.keys(ROUTES).find((k) => ROUTES[k] === name);
  if (view === "detail" && id && state.docs.some((d) => d.id === id)) {
    await openDoc(id, true);
    const tabKey = Object.keys(TABS).find((k) => TABS[k] === tab);
    if (tabKey) showTab(tabKey);
  } else if (view && view !== "detail") {
    go(view);
  }
}

/** Switch between views. */
function go(view) {
  if (view === "detail" && !state.current) {
    if (!state.docs.length) return $("#document-required").showModal();
    return openDoc(state.docs[0].id);
  }
  state.view = view;
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== `view-${view}`));
  $("#more-sheet").classList.add("hidden");
  const secondary = ["types", "wizard", "settings", "help"].includes(view);
  if (view === "wizard") openWizard();
  $("#more-btn").classList.toggle("active", secondary);
  document.querySelectorAll(".rail-btn[data-go]").forEach((b) => {
    const active = b.dataset.go === (view === "wizard" ? "types" : view);
    b.classList.toggle("active", active);
    if (active) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  if (view === "assistant") $("#ask-input").focus();
  setHash(view);
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

/** One-line status under the file name: ready, fields to review, or outside the pool. */
function fileStatus(doc, review) {
  if (!doc.doc_type) return '<div class="file-sub">pusty JSON <code>{}</code></div>';
  if (review) return `<div class="file-sub warn">${review} ${plural(review, "pole", "pola", "pól")} do weryfikacji</div>`;
  return '<div class="file-sub ok">Gotowe</div>';
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
        <div><div class="file-name"><span class="fname-text">${esc(d.filename)}</span>${d.ocr ? '<span class="tag-ocr" title="Skan odczytany przez OCR">OCR</span>' : ""}</div>${fileStatus(d, review)}</div></div></td>
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
  return !c.reference || !c.consistent || c.missing_types.length > 0 || c.formal === "error";
}

const CHECK_STATUS = { ok: ["ok", "Bez uwag"], warn: ["warn", "Do sprawdzenia"], error: ["bad", "Błędy formalne"] };
const CHECK_ICON = {
  ok: '<svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  warn: '<svg viewBox="0 0 24 24"><path d="M12 8v5M12 16.5v.5"/><path d="M10.3 3.9L2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
  error: '<svg viewBox="0 0 24 24"><path d="M7 7l10 10M17 7L7 17"/></svg>',
  skip: '<svg viewBox="0 0 24 24"><path d="M6 12h12"/></svg>',
};

/** Render the formal checklist of one case. */
function renderChecks(c) {
  if (!c.checks || !c.checks.length) return "";
  const [cls, label] = CHECK_STATUS[c.formal] || CHECK_STATUS.ok;
  const skipped = c.checks.filter((k) => k.status === "skip").length;
  const text = skipped ? `${label} · ${skipped} niesprawdzone` : label;
  const items = c.checks.map((k) => `<li class="check ${k.status}" ${k.note ? `title="${esc(k.note)}"` : ""}>
      <span class="check-icon">${CHECK_ICON[k.status] || ""}</span>
      <span class="check-body"><b>${esc(k.label)}</b><small>${esc(k.detail || "")}</small></span></li>`).join("");
  return `<details class="checks" ${c.formal !== "ok" ? "open" : ""}><summary><span>Kontrola formalna</span><span class="status ${cls}">${text}</span></summary><ul>${items}</ul></details>`;
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
          <span class="party">${esc((d.party || []).join(", ") || "—")}</span></li>`).join("")}</ul>${missing}${renderChecks(c)}</article>`;
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

/** Open the detail view of a document and show the guide notice that closes with OK. */
async function openDoc(id, quiet = false) {
  const doc = await api(`/api/documents/${id}`);
  updateDoc(doc);
  $("#summary-card").classList.add("hidden");
  renderDetail(doc);
  state.tab = "json";
  go("detail");
  showTab("json");
  if (!quiet) showDocNotice(doc);
}

/** Show a prominent modal summary of the opened document that closes only when the user clicks OK. */
function showDocNotice(doc) {
  const modal = $("#doc-modal");
  if (!modal) return;
  const fill = completeness(doc);
  const pct = fill === null ? null : Math.round(fill * 100);
  const review = reviewItems(doc);
  const count = review.filter((f) => !state.reviewDone.has(`${doc.id}:${f.field}`)).length;
  const source = doc.ocr ? `skan OCR (${esc(doc.ocr.engine)})` : "warstwa tekstowa PDF";
  const chip = $("#doc-modal-chip");
  const icon = $("#doc-modal-icon");
  const secondary = $("#doc-modal-secondary");
  chip.className = `chip ${doc.doc_type || "none"}`;
  chip.textContent = doc.doc_label || "Spoza puli";
  $("#doc-modal-file").textContent = `${doc.filename} · ${source} · ${doc.seconds.toFixed(2)} s`;

  if (!doc.doc_type) {
    icon.className = "doc-modal-icon warn";
    icon.innerHTML = ICON_BAD;
    $("#doc-modal-title").textContent = "Nie udało się dopasować typu dokumentu";
    $("#doc-modal-body").innerHTML = `<p>${esc(doc.message || "Dokument nie pasuje do odwołania, pełnomocnictwa ani potwierdzenia przelewu.")}</p>
      <div class="doc-modal-tips">
        <div><b>Pusty JSON:</b> zgodnie z wymogami UZP dla dokumentu spoza skonfigurowanych typów wynikiem jest pusty obiekt <code>{}</code>.</div>
        <div><b>Wymuszenie typu:</b> jeśli dokument należy do znanej kategorii, wybierz typ z listy w prawym górnym rogu karty wyniku.</div>
      </div>`;
    secondary.classList.add("hidden");
  } else if (count > 0) {
    icon.className = "doc-modal-icon warn";
    icon.innerHTML = ICON_BAD;
    $("#doc-modal-title").textContent = `${count} ${plural(count, "pole wymaga", "pola wymagają", "pól wymaga")} weryfikacji`;
    $("#doc-modal-body").innerHTML = `<p>Rozpoznano <b>${esc(doc.doc_label)}</b> (kompletność pól: <b>${pct}%</b>). Część pól pozostała pusta, ma kilka pasujących wartości lub różni się od odczytu LLM.</p>
      <div class="doc-modal-tips">
        <div><b>Weryfikacja:</b> sprawdź wskazany fragment dokumentu i popraw lub zatwierdź wartość.</div>
        <div><b>Źródła:</b> kliknij dowolne pole, aby podświetlić jego dokładne miejsce na stronie PDF po lewej.</div>
      </div>`;
    secondary.textContent = "Przejdź do weryfikacji";
    secondary.classList.remove("hidden");
    secondary.onclick = () => { modal.classList.add("hidden"); showTab("review"); };
  } else {
    icon.className = "doc-modal-icon ok";
    icon.innerHTML = ICON_OK;
    $("#doc-modal-title").textContent = `Dokument gotowy (${pct}% kompletności)`;
    $("#doc-modal-body").innerHTML = `<p>Rozpoznano <b>${esc(doc.doc_label)}</b>. Wszystkie wymagane pola mają jednoznaczne źródło w dokumencie.</p>
      <div class="doc-modal-tips">
        <div><b>Podgląd i JSON:</b> po lewej stronie widzisz strony PDF, a po prawej gotowy wynik JSON zgodny ze schematem UZP.</div>
        <div><b>Źródła w PDF:</b> otwórz zakładkę <b>Źródła</b> i kliknij dowolne pole, aby podświetlić wartość bezpośrednio na stronie dokumentu.</div>
      </div>`;
    secondary.textContent = "Pokaż źródła pól";
    secondary.classList.remove("hidden");
    secondary.onclick = () => { modal.classList.add("hidden"); showTab("fields"); };
  }
  modal.classList.remove("hidden");
  $("#doc-modal-ok").focus();
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
  if ($("#d-pdf").dataset.id !== doc.id) {
    $("#d-pdf").dataset.id = doc.id;
    renderPages(doc);
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

/** Highlight where a field value sits in the PDF preview and scroll to it. */
async function locateField(doc, field) {
  state.located = field;
  document.querySelectorAll(".src.located").forEach((el) => el.classList.remove("located"));
  document.querySelectorAll(".src.clickable").forEach((el) => { if (doc.fields[Number(el.dataset.field)].field === field) el.classList.add("located"); });
  document.querySelectorAll("#d-pdf .hl").forEach((el) => el.remove());
  const res = await api(`/api/documents/${doc.id}/locate/${encodeURIComponent(field)}`).catch(() => ({ boxes: [] }));
  if (!res.boxes.length) {
    toast(res.reason || "Nie znaleziono tego fragmentu w warstwie tekstowej PDF. Pokazuję go w zakładce Tekst.");
    const f = doc.fields.find((x) => x.field === field);
    if (f && f.start !== null) { showTab("text"); renderText(doc, [f.start, f.end]); }
    return;
  }
  const figures = document.querySelectorAll("#d-pdf .page");
  let first = null;
  res.boxes.forEach(({ page, rects }) => {
    const fig = figures[page - 1];
    if (!fig) return;
    const holder = fig.querySelector(".page-img");
    const layer = holder.querySelector(".hl-layer") || holder.appendChild(Object.assign(document.createElement("div"), { className: "hl-layer" }));
    rects.forEach(([x0, y0, x1, y1]) => {
      const pad = 0.003;
      const el = Object.assign(document.createElement("div"), { className: "hl", title: field });
      Object.assign(el.style, { left: `${(x0 - pad) * 100}%`, top: `${(y0 - pad) * 100}%`, width: `${(x1 - x0 + 2 * pad) * 100}%`, height: `${(y1 - y0 + 2 * pad) * 100}%` });
      layer.appendChild(el);
      first = first || el;
    });
  });
  if (first) first.scrollIntoView({ behavior: "smooth", block: "center" });
}

/** Render the PDF preview as server-rendered page images (works without a browser PDF plugin). */
async function renderPages(doc) {
  state.located = null;
  const box = $("#d-pdf");
  box.innerHTML = '<div class="empty-state"><span class="spinner"></span></div>';
  try {
    const { pages } = await api(`/api/documents/${doc.id}/pages`);
    box.innerHTML = `<div class="pages">${Array.from({ length: pages }, (_, i) => `
      <figure class="page"><div class="page-img"><img loading="${i < 2 ? "eager" : "lazy"}" src="/api/documents/${doc.id}/pages/${i + 1}.png" alt="Strona ${i + 1} z ${pages}: ${esc(doc.filename)}"></div><figcaption>Strona ${i + 1} z ${pages}</figcaption></figure>`).join("")}</div>`;
  } catch (e) {
    box.innerHTML = `<div class="empty-state"><b>Nie udało się wyświetlić podglądu</b><a class="btn" href="/api/documents/${doc.id}/pdf" target="_blank">Otwórz PDF</a></div>`;
  }
}

/** Flatten nested values into path → leaf pairs for a readable comparison. */
function flatten(value, prefix = "", out = {}) {
  if (Array.isArray(value)) value.forEach((v, i) => flatten(v, `${prefix}[${i}]`, out));
  else if (value && typeof value === "object") Object.entries(value).forEach(([k, v]) => flatten(v, prefix ? `${prefix}.${k}` : k, out));
  else out[prefix] = value;
  return out;
}

/** Only the sub-fields where the rules and the LLM disagree. */
function differences(rules, llm) {
  const a = flatten(rules ?? null);
  const b = flatten(llm ?? null);
  const norm = (v) => (v === null || v === undefined ? "" : String(v).trim().toLowerCase().replace(/\s+/g, " "));
  return [...new Set([...Object.keys(a), ...Object.keys(b)])].filter((k) => norm(a[k]) !== norm(b[k])).map((k) => ({ path: k, rules: a[k], llm: b[k] }));
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
      ${llm !== null ? renderDiff(f) : ""}
      ${f.review_context || f.snippet ? `<div class="review-context">${esc(f.review_context || f.snippet)}</div>` : ""}
      <div class="review-edit">${input}
        <button class="btn primary" data-save="${esc(f.field)}">Zapisz</button>
        ${llm !== null ? `<button class="btn" data-use-llm="${esc(f.field)}">Użyj wartości LLM</button>` : ""}
        <button class="btn" data-accept="${esc(f.field)}">${shown ? "Zatwierdź" : "Zostaw puste"}</button>
        ${f.start !== null && f.start !== undefined ? `<button class="btn ghost" data-locate="${esc(f.field)}">Zaznacz w PDF</button>` : ""}
      </div></div>`;
  }).join("")}</div>`;
}

/** Show the rules and LLM values side by side, limited to the sub-fields that differ. */
function renderDiff(f) {
  const show = (v) => (v === null || v === undefined || v === "" ? '<span class="muted">brak</span>' : esc(v));
  const diffs = differences(f.value, f.llm_value);
  if (!diffs.length) return "";
  const rows = diffs.slice(0, 8).map((d) => `<tr><td class="mono">${esc(d.path || f.field)}</td><td>${show(d.rules)}</td><td>${show(d.llm)}</td></tr>`).join("");
  const more = diffs.length > 8 ? `<p class="muted small">…i ${diffs.length - 8} ${plural(diffs.length - 8, "inna różnica", "inne różnice", "innych różnic")}</p>` : "";
  return `<table class="diff"><thead><tr><th>Pole</th><th>Reguły</th><th>LLM</th></tr></thead><tbody>${rows}</tbody></table>${more}`;
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
    return `<div class="src ${clickable ? "clickable" : ""} ${state.located === f.field ? "located" : ""}" data-field="${i}" ${clickable ? 'tabindex="0"' : ""}>
      <div class="src-top"><span class="src-name">${esc(f.field)}${flags}</span><span class="src-method">${esc(f.source)} · ${esc(f.method || "brak dopasowania")}</span></div>
      <div class="src-value">${value === null || value === undefined ? '<span class="muted">null</span>' : esc(value)}</div>
      ${f.snippet ? `<div class="src-snip">„…${esc(f.snippet)}…”</div>` : ""}
      ${clickable ? `<div class="src-actions"><span class="src-hint">Kliknij, aby zaznaczyć w dokumencie</span><button class="link-btn" data-show-text="${i}">Pokaż w tekście</button></div>` : ""}</div>`;
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
  state.tab = name;
  if (state.view === "detail") setHash("detail", name);
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

/** Download the current PDF with personal data blacked out and report what was covered. */
async function anonymizePdf() {
  const doc = state.current;
  if (!doc) return;
  try {
    const response = await busy("Zaczerniam dane osobowe…", () => fetch(`/api/documents/${doc.id}/anonymized.pdf`));
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || response.statusText);
    const counts = JSON.parse(response.headers.get("X-Redacted") || "{}");
    const url = URL.createObjectURL(await response.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: doc.filename.replace(/\.pdf$/i, "_anonimizacja.pdf") });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    const names = { osoba: "nazwiska i imiona", dane: "dane z pól", pesel: "PESEL", email: "e-maile", telefon: "telefony" };
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    toast(total ? `Zaczerniono ${total}: ${Object.entries(counts).map(([k, v]) => `${names[k] || k} ${v}`).join(", ")}` : "Nie znaleziono danych osobowych do zaczernienia");
  } catch (e) {
    toast(e.message);
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
  status.textContent = enabled ? `LLM: ${String(model).split("/").pop().replace(/-GGUF.*$/i, "").replace(/:.*$/, "")}` : "LLM: wyłączony";
  status.title = enabled ? String(model) : "";
  status.className = enabled ? (accurate ? "accurate" : "on") : "";
  document.querySelectorAll(".llm-only").forEach((b) => {
    b.disabled = !enabled;
    b.title = enabled ? "" : "Włącz model językowy w Ustawieniach";
  });
  $("#assistant-off").classList.toggle("hidden", enabled);
  $("#ask-btn").textContent = enabled ? "Zapytaj" : "Szukaj";
  document.querySelectorAll("#mode-switch button").forEach((b) => {
    const on = b.dataset.mode === (mode || "fast");
    b.classList.toggle("active", on);
    b.setAttribute("aria-checked", String(on));
  });
}

/** Highlight the preset card matching the current URL and model inputs. */
function syncPresetHighlight() {
  const url = ($("#llm-url")?.value || "").trim().replace(/\/+$/, "");
  const model = ($("#llm-model")?.value || "").trim();
  document.querySelectorAll("#llm-presets .preset-card").forEach((card) => {
    const sameUrl = card.dataset.url.replace(/\/+$/, "") === url;
    const sameModel = card.dataset.model === model;
    card.classList.toggle("active", sameUrl && sameModel);
  });
}

/** Update the visual connection status box in LLM settings. */
function setLlmStatusBox(kind, title, detail) {
  const box = $("#llm-check-box");
  if (box) box.className = `llm-status-box ${kind}`;
  const t = $("#llm-check-title");
  if (t) t.textContent = title;
  const out = $("#llm-check-out");
  if (out) {
    out.className = kind === "ok" ? "ok" : kind === "err" ? "err" : "muted";
    out.innerHTML = detail;
  }
}

/** Render discovered models from the endpoint as clickable chips and datalist options. */
function renderDiscoveredModels(models = []) {
  const list = $("#llm-models-list");
  if (list) list.innerHTML = models.map((m) => `<option value="${esc(m)}">`).join("");
  const box = $("#llm-discovered");
  if (!box) return;
  if (!models.length) {
    box.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
  const current = ($("#llm-model")?.value || "").trim();
  box.classList.remove("hidden");
  box.innerHTML = `<span class="field-hint">Modele dostępne na serwerze (${models.length}):</span><div class="llm-model-chips">${models.slice(0, 12).map((m) => `<button type="button" class="chip ${m === current ? "ok" : "neutral"}" data-pick-model="${esc(m)}">${esc(m)}</button>`).join("")}</div>`;
}

/** Fill the LLM settings form from the server. */
async function loadLlm() {
  state.llm = await api("/api/llm");
  $("#llm-enabled").checked = state.llm.enabled;
  $("#llm-enabled-label").textContent = state.llm.enabled ? "Włączony" : "Wyłączony";
  $("#llm-url").value = state.llm.base_url;
  $("#llm-model").value = state.llm.model;
  $("#llm-key").value = "";
  $("#llm-key-hint").textContent = state.llm.has_key ? "Klucz API jest zapisany na serwerze." : "Brak zapisanego klucza (niepotrzebny dla lokalnej Ollamy / vLLM).";
  syncPresetHighlight();
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
  setLlmStatusBox("testing", "Testowanie połączenia…", '<span class="spinner" style="display:inline-block;vertical-align:middle"></span> Sprawdzam listę modeli i próbne zapytanie JSON…');
  await send("/api/llm", "PUT", llmForm());
  const r = await api("/api/llm/check", { method: "POST" });
  if (r.ok) {
    renderDiscoveredModels(r.models || []);
    const count = (r.models || []).length;
    setLlmStatusBox("ok", "Połączenie działa poprawnie", esc(`Model ${r.model} odpowiedział poprawnym JSON-em w ${r.seconds} s${count ? ` (dostępnych modeli na serwerze: ${count})` : ""}.`));
  } else {
    setLlmStatusBox("err", "Błąd połączenia z modelem", esc(`Błąd: ${r.error}`));
  }
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

/** Mark query words (by their stems) inside a snippet. */
function markTerms(text, terms) {
  const fold = (w) => w.normalize("NFKD").replace(/ł/g, "l").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  return esc(text).replace(/[\p{L}\d]+/gu, (w) => (w.length >= 3 && terms.some((t) => fold(w).startsWith(t)) ? `<mark>${w}</mark>` : w));
}

/** Show the best matching fragments without a language model. */
async function searchDocuments(question, box) {
  try {
    const { hits } = await send("/api/search", "POST", { question });
    box.querySelector(".answer-a").innerHTML = hits.length
      ? `<span class="muted">Najtrafniejsze fragmenty (${hits.length}) · wyszukiwanie lokalne bez modelu</span>`
      : "Nie znalazłem fragmentów pasujących do zapytania.";
    box.insertAdjacentHTML("beforeend", `<div class="answer-sources">${hits.map((h, i) => `
      <button class="source" data-doc="${h.doc_id}" data-start="${h.start}" data-end="${h.end}">
        <span class="source-n">${i + 1}</span><span><span class="source-file">${esc(h.filename)}</span><span class="source-snip">${markTerms(h.snippet, h.terms)}</span></span></button>`).join("")}</div>`);
  } catch (e) {
    box.querySelector(".answer-a").textContent = `Błąd: ${e.message}`;
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
  if (!state.llm.enabled) return searchDocuments(question, box);
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

const wz = { doc: null, fields: {}, selection: null, timer: null, touchedName: false };

/** Parse "phrase: weight" lines into a keyword map. */
function parseWeights(text) {
  const out = {};
  text.split("\n").map((l) => l.trim()).filter(Boolean).forEach((line) => {
    const at = line.lastIndexOf(":");
    const weight = at > 0 ? Number(line.slice(at + 1)) : NaN;
    out[(Number.isFinite(weight) ? line.slice(0, at) : line).trim()] = Number.isFinite(weight) ? weight : 1;
  });
  return out;
}

/** Format a keyword map as "phrase: weight" lines. */
function formatWeights(map) {
  return Object.entries(map || {}).map(([k, v]) => `${k}: ${v}`).join("\n");
}

/** Identifier from a display name (ASCII, lowercase, underscores). */
function slugify(text) {
  return text.normalize("NFKD").replace(/ł/g, "l").replace(/Ł/g, "L").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40);
}

/** The current wizard draft in the YAML structure of a document type. */
function wizardDraft() {
  return {
    name: $("#wz-name").value.trim() || slugify($("#wz-label").value) || "nowy_typ",
    label: $("#wz-label").value.trim() || "Nowy typ",
    classify: { head_chars: 800, head_keywords: parseWeights($("#wz-head").value), keywords: parseWeights($("#wz-kw").value) },
    fields: wz.fields,
  };
}

/** Open the wizard with the first text document as the sample. */
async function openWizard() {
  const docs = state.docs;
  $("#wz-doc").innerHTML = docs.length
    ? docs.map((d) => `<option value="${d.id}">${esc(d.filename)} · ${esc(d.doc_label)}</option>`).join("")
    : '<option value="">Najpierw dodaj przykładowy PDF</option>';
  if (!docs.length) {
    $("#wz-text").textContent = "Dodaj przykładowy PDF przyciskiem obok.";
    return;
  }
  const pick = docs.find((d) => d.id === wz.doc) || docs.find((d) => !d.doc_type) || docs[0];
  $("#wz-doc").value = pick.id;
  await selectSample(pick.id, !Object.keys(wz.fields).length);
}

/** Show a sample document and optionally suggest keywords from it. */
async function selectSample(id, suggest) {
  wz.doc = id;
  const doc = await api(`/api/documents/${id}`).catch(() => null);
  $("#wz-text").textContent = doc && doc.text ? doc.text : "Ten dokument nie ma tekstu.";
  if (suggest) {
    const kw = await api(`/api/wizard/keywords/${id}`).catch(() => ({}));
    $("#wz-head").value = formatWeights(kw.head_keywords);
    $("#wz-kw").value = formatWeights(kw.keywords);
  }
  schedulePreview();
}

/** Character offsets of the current selection inside the sample text. */
function selectionOffsets() {
  const sel = window.getSelection();
  const box = $("#wz-text");
  if (!sel.rangeCount || sel.isCollapsed) return null;
  const range = sel.getRangeAt(0);
  if (!box.contains(range.startContainer) || !box.contains(range.endContainer)) return null;
  const pre = document.createRange();
  pre.selectNodeContents(box);
  pre.setEnd(range.startContainer, range.startOffset);
  const start = pre.toString().length;
  return { start, end: start + range.toString().length, text: range.toString() };
}

/** Reflect the current selection in the selection bar. */
function updateSelection() {
  if (state.view !== "wizard") return;
  const sel = selectionOffsets();
  if (sel && sel.text.trim()) wz.selection = sel;
  else if (!sel) return;
  $("#wz-selection").innerHTML = wz.selection ? `Zaznaczono: <b>${esc(wz.selection.text.trim().slice(0, 60))}</b>` : "Nic nie zaznaczono";
  $("#wz-add").disabled = !wz.selection;
}

/** Turn the selection into a field with a suggested rule. */
async function addWizardField() {
  if (!wz.selection || !wz.doc) return;
  try {
    const s = await api("/api/wizard/suggest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ doc_id: wz.doc, start: wz.selection.start, end: wz.selection.end }) });
    let name = s.name;
    for (let i = 2; wz.fields[name]; i++) name = `${s.name}_${i}`;
    wz.fields[name] = s.field;
    wz.selection = null;
    window.getSelection().removeAllRanges();
    $("#wz-selection").textContent = "Nic nie zaznaczono";
    $("#wz-add").disabled = true;
    renderWizardFields();
    schedulePreview();
  } catch (e) {
    toast(e.message);
  }
}

/** Describe a field rule in a short human readable form. */
function ruleText(spec) {
  const rule = (spec.extract || [])[0] || {};
  if (rule.type === "label") return `po etykiecie „${(rule.labels || [""])[0].replace(/\\s\+/g, " ").replace(/\\/g, "")}”${rule.until ? " (wiele linii)" : ""}`;
  if (rule.type === "regex" && rule.occurrence === undefined) return spec.description || "wzorzec";
  if (rule.type === "regex") return `wzorzec, wystąpienie ${rule.occurrence + 1}`;
  return rule.type || "—";
}

/** Render the list of wizard fields with their rules and values. */
function renderWizardFields(values = {}) {
  const names = Object.keys(wz.fields);
  $("#wz-fields").innerHTML = names.length ? names.map((n) => {
    const f = wz.fields[n];
    const v = values[n];
    return `<div class="wz-field">
      <div class="wz-field-top"><input class="wz-fname mono" value="${esc(n)}" data-rename="${esc(n)}" aria-label="Nazwa pola">
        <span class="chip neutral">${esc((f.normalize || []).join(", ") || "tekst")}</span>
        <button class="icon-btn danger" data-remove="${esc(n)}" title="Usuń pole" aria-label="Usuń pole ${esc(n)}">${ICON_TRASH}</button></div>
      <div class="wz-rule">${esc(ruleText(f))}</div>
      <div class="wz-value ${v === null || v === undefined ? "empty" : ""}">${v === null || v === undefined ? "brak wartości" : esc(typeof v === "object" ? JSON.stringify(v) : v)}</div></div>`;
  }).join("") : '<div class="empty-state small"><b>Brak pól</b><span>Zaznacz wartość w tekście po lewej i kliknij „Dodaj jako pole”.</span></div>';
}

/** Re-run the preview shortly after the last change. */
function schedulePreview() {
  clearTimeout(wz.timer);
  wz.timer = setTimeout(runPreview, 250);
}

/** Run the draft type on the sample and show the result, score and collisions. */
async function runPreview() {
  if (!wz.doc) return;
  try {
    const p = await api("/api/wizard/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ doc_id: wz.doc, draft: wizardDraft() }) });
    const values = Object.fromEntries(p.fields.map((f) => [f.field, f.value]));
    renderWizardFields(values);
    $("#wz-json").innerHTML = highlight(p.data);
    $("#wz-yaml").textContent = p.yaml;
    $("#wz-status").innerHTML = p.recognized
      ? `<span class="ok-text">Przykład rozpoznany</span> · ${p.score} pkt (${esc(p.hits.join(", "))})`
      : `<span class="warn">Przykład nierozpoznany</span> · ${p.score} pkt. Dodaj frazę z nagłówka z wagą 5.`;
    const collisions = p.samples.filter((x) => x.matches && x.doc_type);
    const alike = p.samples.filter((x) => x.matches && !x.doc_type);
    const parts = [];
    if (alike.length) parts.push(`<div class="wz-ok">Pasuje też do ${alike.length} ${plural(alike.length, "innego dokumentu", "innych dokumentów", "innych dokumentów")} spoza puli: ${alike.map((x) => `<b>${esc(x.filename)}</b> (${x.filled}/${p.field_count} pól)`).join(", ")}.</div>`);
    if (collisions.length) parts.push(`<div class="wz-collide">Koliduje z istniejącym typem: ${collisions.map((x) => `<b>${esc(x.filename)}</b> (${esc(x.doc_label)}, ${x.score} pkt)`).join(", ")}. Dodaj frazę charakterystyczną tylko dla tego typu albo zmniejsz wagi fraz wspólnych.</div>`);
    if (!parts.length && p.samples.length) parts.push(`<div class="wz-ok">Nie koliduje z ${p.samples.length} ${plural(p.samples.length, "innym dokumentem", "innymi dokumentami", "innymi dokumentami")}.</div>`);
    $("#wz-samples").innerHTML = parts.join("");
  } catch (e) {
    $("#wz-status").innerHTML = `<span class="warn">${esc(e.message)}</span>`;
  }
}

/** Save the draft as a YAML type, reload types and reprocess documents outside the pool. */
async function saveWizard(overwrite = false) {
  if (!Object.keys(wz.fields).length) return toast("Dodaj co najmniej jedno pole");
  try {
    const res = await api("/api/types", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ draft: wizardDraft(), overwrite }) });
    for (const d of state.docs.filter((x) => !x.doc_type)) {
      updateDoc(await api(`/api/documents/${d.id}/reprocess`, { method: "POST" }));
    }
    wz.fields = {};
    ["#wz-label", "#wz-name", "#wz-head", "#wz-kw"].forEach((s) => { $(s).value = ""; });
    await loadInfo();
    await refreshCases();
    go("types");
    toast(`Zapisano typ ${res.name} (${res.path.split(/[\\/]/).slice(-2).join("/")})`);
  } catch (e) {
    if (/już istnieje/.test(e.message) && window.confirm(`${e.message} Nadpisać?`)) return saveWizard(true);
    toast(e.message);
  }
}

/** Load app info, document types and update status. */
async function loadInfo() {
  const info = await api("/api/info");
  state.types = info.types;
  $("#d-type").innerHTML = '<option value="">Typ: automatycznie</option>' + info.types.map((t) => `<option value="${esc(t.name)}">${esc(t.label)}</option>`).join("");
  $("#types").innerHTML = info.types.map((t) => `<div class="card type-card ${t.source && !["odwolanie.yaml", "pelnomocnictwo.yaml", "przelew.yaml"].includes(t.source) ? "custom" : ""}">
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
  $("#document-required").addEventListener("cancel", event => event.preventDefault());
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
    if (e.target.closest("[data-show-text]")) {
      showTab("text");
      renderText(state.current, [f.start, f.end]);
      return;
    }
    locateField(state.current, f.field);
  });
  $("#d-review").addEventListener("click", (e) => {
    const save = e.target.closest("[data-save]");
    const use = e.target.closest("[data-use-llm]");
    const accept = e.target.closest("[data-accept]");
    const locate = e.target.closest("[data-locate]");
    if (locate) return locateField(state.current, locate.dataset.locate);
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
    await openDoc(state.current.id, true);
    refreshCases();
  });
  $("#btn-copy").addEventListener("click", copyJson);
  $("#btn-anon").addEventListener("click", anonymizePdf);
  $("#d-copy").addEventListener("click", copyJson);
  $("#btn-llm").addEventListener("click", refineWithLlm);
  $("#btn-summary").addEventListener("click", showSummary);
  $("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); askQuestion($("#ask-input").value); });
  $("#ask-examples").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b && state.llm.enabled) askQuestion(b.textContent); });
  $("#answers").addEventListener("click", async (e) => {
    const s = e.target.closest(".source");
    if (!s) return;
    await openDoc(s.dataset.doc, true);
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
  $("#doc-modal-ok")?.addEventListener("click", () => $("#doc-modal").classList.add("hidden"));
  $("#llm-presets")?.addEventListener("click", (e) => {
    const card = e.target.closest(".preset-card");
    if (!card) return;
    $("#llm-url").value = card.dataset.url;
    $("#llm-model").value = card.dataset.model;
    $("#llm-enabled").checked = true;
    $("#llm-enabled-label").textContent = "Włączony";
    syncPresetHighlight();
    if (card.dataset.needKey === "1" && !state.llm.has_key) $("#llm-key").focus();
    toast(`Wybrano profil: ${card.querySelector("b").textContent}`);
  });
  $("#llm-discovered")?.addEventListener("click", (e) => {
    const b = e.target.closest("[data-pick-model]");
    if (!b) return;
    $("#llm-model").value = b.dataset.pickModel;
    syncPresetHighlight();
    document.querySelectorAll("#llm-discovered [data-pick-model]").forEach((el) => {
      el.className = `chip ${el.dataset.pickModel === b.dataset.pickModel ? "ok" : "neutral"}`;
    });
  });
  $("#llm-url")?.addEventListener("input", syncPresetHighlight);
  $("#llm-model")?.addEventListener("input", syncPresetHighlight);
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
  $("#btn-new-type").addEventListener("click", () => go("wizard"));
  $("#wz-cancel").addEventListener("click", () => go("types"));
  $("#wz-save").addEventListener("click", () => saveWizard());
  $("#wz-doc").addEventListener("change", (e) => selectSample(e.target.value, !Object.keys(wz.fields).length));
  $("#wz-upload").addEventListener("click", () => $("#wz-file").click());
  $("#wz-file").addEventListener("change", async (e) => {
    const form = new FormData();
    [...e.target.files].forEach((f) => form.append("files", f));
    e.target.value = "";
    try {
      const results = await busy("Wczytuję przykład…", () => api("/api/documents", { method: "POST", body: form }));
      state.docs.push(...results);
      renderTable();
      if (results[0]) { wz.doc = results[0].id; openWizard(); }
    } catch (err) { toast(err.message); }
  });
  document.addEventListener("selectionchange", updateSelection);
  $("#wz-add").addEventListener("click", addWizardField);
  $("#wz-label").addEventListener("input", () => { if (!wz.touchedName) $("#wz-name").value = slugify($("#wz-label").value); schedulePreview(); });
  $("#wz-name").addEventListener("input", () => { wz.touchedName = true; });
  ["#wz-head", "#wz-kw"].forEach((sel) => $(sel).addEventListener("input", schedulePreview));
  $("#wz-fields").addEventListener("click", (e) => {
    const b = e.target.closest("[data-remove]");
    if (!b) return;
    delete wz.fields[b.dataset.remove];
    renderWizardFields();
    schedulePreview();
  });
  $("#wz-fields").addEventListener("change", (e) => {
    const input = e.target.closest("[data-rename]");
    if (!input) return;
    const old = input.dataset.rename;
    const name = slugify(input.value) || old;
    if (name !== old && !wz.fields[name]) {
      wz.fields = Object.fromEntries(Object.entries(wz.fields).map(([k, v]) => [k === old ? name : k, v]));
    }
    renderWizardFields();
    schedulePreview();
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
window.addEventListener("hashchange", applyRoute);
loadInfo().then(loadLlm).then(() => api("/api/documents")).then(async (docs) => { state.docs = docs || []; renderTable(); await refreshCases(); await applyRoute(); document.body.dataset.ready = "1"; });
