/* Vendor Onboarding Autopilot — single-page UI (no build step). */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const view = $("#view");
let META = null;
let cleanup = [];

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}
function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = msg; document.body.appendChild(t);
  setTimeout(() => t.remove(), 2800);
}

/* ---------------------------------------------------------------- icons */
const I = {
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  bang: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M12 6v8M12 18.5v.01"/></svg>',
  clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>',
  spin: '<svg class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M12 3a9 9 0 019 9"/></svg>',
  info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5v.01"/></svg>',
  okc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16 9.8"/></svg>',
  warn: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.5l9.5 16.5h-19z"/><path d="M12 10v4.5M12 17.5v.01"/></svg>',
  eye: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M8.5 8.5l7 7M15.5 8.5l-7 7"/></svg>',
  doc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/></svg>',
  up: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4M7 9l5-5 5 5M5 20h14"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13l10.5-6.5z"/></svg>',
  reply: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 14L4 9l5-5"/><path d="M4 9h11a5 5 0 015 5v6"/></svg>',
  spark: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2.5l1.9 5.6 5.6 1.9-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.9zM19 15l.9 2.1 2.1.9-2.1.9L19 21l-.9-2.1-2.1-.9 2.1-.9z"/></svg>',
  send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12l16-8-6 16-2.5-6.5z"/></svg>',
  bolt: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M13 2L4 14h7l-1 8 9-12h-7z"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>',
};
const STATUS_ICON = { APPROVED: I.check, PENDING: I.clock, REJECTED: I.x, RUNNING: I.spin, ERROR: I.bang };
const STATUS_LABEL = { APPROVED: "Approved", PENDING: "Pending", REJECTED: "Rejected", RUNNING: "Running", ERROR: "Error" };
const SEV_ICON = { pass: I.okc, info: I.info, action: I.warn, review: I.eye, critical: I.stop };
const SEV_LABEL = { pass: "Passed", info: "Note", action: "Vendor action", review: "Needs review", critical: "Critical" };
const AI_NOTE = "AI_OBSERVATION";
function findingHTML(f, extraStyle = "") {
  const ai = f.code === AI_NOTE;
  const q = ai && f.evidence?.quote ? `<div class="fq">“${esc(f.evidence.quote)}” — ${esc(f.evidence.source)}</div>` : "";
  return `<div class="finding ${esc(f.severity)}${ai ? " ai" : ""}" style="${extraStyle}"><div class="ft">${ai ? I.spark : SEV_ICON[f.severity]}<span>${esc(f.title)}</span><span class="sev">${ai ? "AI note" : SEV_LABEL[f.severity]}</span></div>${f.detail ? `<div class="fd">${esc(f.detail)}</div>` : ""}${q}</div>`;
}
const badge = (s, lg = false) => `<span class="badge ${esc(s)} ${lg ? "lg" : ""}">${STATUS_ICON[s] || ""}${esc(STATUS_LABEL[s] || s)}</span>`;

const ISSUE_LABEL = {
  MISSING_FIELD: "Missing form field", MISSING_DOC: "Missing document", DOC_WRONG_SLOT: "Wrong document in slot",
  DOC_UNREADABLE: "Unreadable document", DOC_UNRECOGNISED: "Unrecognised document", DOC_WRONG_COMPANY: "Document for another company",
  TAX_CHECKSUM: "Tax ID typo (check digit)", TAX_FORMAT: "Tax ID wrong format", TAX_JURISDICTION_MISMATCH: "Tax ID from another country",
  TAX_DOC_MISMATCH: "Tax ID ≠ certificate", TAX_UNVERIFIABLE: "Tax ID not auto-verifiable", TAX_INDIVIDUAL_PAN: "Individual PAN",
  IBAN_INVALID: "Invalid IBAN", IBAN_COUNTRY_MISMATCH: "Foreign bank account", BIC_INVALID: "Invalid BIC", BIC_IBAN_MISMATCH: "BIC ≠ IBAN country",
  ROUTING_INVALID: "Invalid routing number", ACCOUNT_INVALID: "Invalid account number", IFSC_INVALID: "Invalid IFSC",
  BANK_LETTER_ACCOUNT_MISMATCH: "Bank letter for other account", BANK_HOLDER_RELATED: "Account holder: related entity",
  BANK_HOLDER_MISMATCH: "Account holder: unrelated", BANK_HOLDER_UNREAD: "Account holder unreadable",
  INSURANCE_EXPIRED: "Insurance expired", INSURANCE_NO_EXPIRY: "Insurance expiry unreadable", INSURANCE_COVER_LOW: "Insurance cover too low",
  BANK_LETTER_STALE: "Bank letter too old", DOC_FUTURE_DATED: "Future-dated document",
  BANK_ACCOUNT_IN_USE: "Bank account used by another vendor", TAX_ID_IN_USE: "Tax ID used by another vendor",
  DUPLICATE_VENDOR: "Duplicate vendor", BANK_CHANGED_UNPROMPTED: "Unrequested bank change", CONTACT_DOMAIN_CHANGED: "Contact domain changed",
  BEC_PATTERN: "Email-compromise pattern", PREVIOUSLY_REJECTED: "Previously rejected", BAD_EMAIL: "Invalid email",
  COUNTRY_UNSUPPORTED: "Unsupported country", BANK_SCHEME_UNKNOWN: "No bank rules for country",
};

const fmtTime = (iso) => { if (!iso) return "—"; const d = new Date(iso); return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); };
const ago = (iso) => { const s = (Date.now() - new Date(iso)) / 1000; if (s < 60) return "just now"; if (s < 3600) return `${Math.floor(s / 60)} min ago`; if (s < 86400) return `${Math.floor(s / 3600)} h ago`; return fmtTime(iso); };
const country = (c) => (META?.countries?.[c] || c || "—");

/* ---------------------------------------------------------------- router */
const routes = { dashboard: renderDashboard, new: renderNew, run: renderRun, vendors: renderVendors, outbox: renderOutbox, how: renderHow };
async function route() {
  cleanup.forEach((f) => f()); cleanup = [];
  const [path, query] = (location.hash.replace(/^#\/?/, "") || "dashboard").split("?");
  const [name, arg] = path.split("/");
  $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.r === name || (name === "run" && a.dataset.r === "dashboard")));
  const params = new URLSearchParams(query || "");
  window.scrollTo(0, 0);
  try { await (routes[name] || renderDashboard)(arg, params); }
  catch (e) { view.innerHTML = `<div class="card card-pad">Something went wrong: ${esc(e.message)}</div>`; console.error(e); }
}
window.addEventListener("hashchange", route);

/* ---------------------------------------------------------------- dashboard */
async function renderDashboard() {
  let filter = sessionStorage.getItem("dash-filter") || "all";
  let q = "";
  view.innerHTML = `
    <div class="page-head">
      <div><h1>Onboarding dashboard</h1><p>Every submission, its outcome, and what it is waiting on.</p></div>
      <div class="actions">
        <button class="btn" id="seed">${I.bolt}Run all test scenarios</button>
        <button class="btn" id="reset">${I.trash}Reset demo data</button>
        <a class="btn primary" href="#/new">${I.up}New submission</a>
      </div>
    </div>
    <div class="kpis" id="kpis"></div>
    <div class="grid-2">
      <div class="card card-pad"><h2>Outcomes</h2><div class="muted small">Share of final decisions (superseded attempts excluded)</div><div id="seg"></div>
        <h3 style="margin-top:18px">Needs attention</h3><div class="muted small">Open pending cases, oldest first</div><ul class="attn" id="attn"></ul></div>
      <div class="card card-pad"><h2>Why vendors get stuck</h2><div class="muted small">Most frequent open issues across all runs</div><div class="meters" id="meters" style="margin-top:12px"></div></div>
    </div>
    <div class="card">
      <div class="toolbar">
        <div class="seg" id="filters">
          ${["all", "APPROVED", "PENDING", "REJECTED"].map((f) => `<button data-f="${f}">${f === "all" ? "All" : STATUS_LABEL[f]}</button>`).join("")}
        </div>
        <input type="search" class="search" id="q" placeholder="Search vendor, country, run ID…">
        <span class="muted small" id="count" style="margin-left:auto"></span>
      </div>
      <div class="table-wrap"><table class="t"><thead><tr>
        <th>Vendor</th><th>Status</th><th>Risk</th><th>Main issue / next step</th><th>Source</th><th>Submitted</th>
      </tr></thead><tbody id="rows"></tbody></table></div>
    </div>`;

  let data = { runs: [], stats: {} };
  const paint = () => {
    const s = data.stats;
    const live = data.runs.filter((r) => !r.superseded_by && r.status !== "RUNNING");
    const kpi = (label, value, sub, icon = "") => `<div class="card kpi"><div class="label">${icon}${label}</div><div class="value">${value}</div><div class="sub">${sub}</div></div>`;
    $("#kpis").innerHTML =
      kpi("Submissions", s.total || 0, `${live.length} distinct outcomes`) +
      kpi("Approved", s.APPROVED || 0, "written to vendor master", `<span style="color:var(--good-ink)">${I.check}</span>`) +
      kpi("Open · pending", s.open || 0, `${data.runs.filter((r) => r.status === "PENDING" && !r.superseded_by && r.waiting_on === "vendor").length} waiting on vendor`, `<span style="color:var(--warn-ink)">${I.clock}</span>`) +
      kpi("Rejected", s.REJECTED || 0, "fraud / duplicate / compounding risk", `<span style="color:var(--crit-ink)">${I.x}</span>`) +
      kpi("Avg. processing", s.avg_ms != null ? (s.avg_ms / 1000).toFixed(1) + "s" : "—", "submission → decision");

    const counts = { APPROVED: 0, PENDING: 0, REJECTED: 0 };
    live.forEach((r) => { if (counts[r.status] != null) counts[r.status]++; });
    const tot = counts.APPROVED + counts.PENDING + counts.REJECTED;
    const col = { APPROVED: "var(--good)", PENDING: "var(--warn)", REJECTED: "var(--crit)" };
    $("#seg").innerHTML = tot ? `
      <div class="segbar" role="img" aria-label="${Object.entries(counts).map(([k, v]) => `${STATUS_LABEL[k]} ${v}`).join(", ")}">
        ${Object.entries(counts).filter(([, v]) => v).map(([k, v]) => `<div style="flex-grow:${v};background:${col[k]}" title="${STATUS_LABEL[k]}: ${v} (${Math.round((v / tot) * 100)}%)"></div>`).join("")}
      </div>
      <div class="legend">${Object.entries(counts).map(([k, v]) => `<span><i style="background:${col[k]}"></i>${STATUS_ICON[k].replace("<svg", '<svg width="12" height="12"')} ${STATUS_LABEL[k]} <b>${v}</b> <span class="muted">${tot ? Math.round((v / tot) * 100) : 0}%</span></span>`).join("")}</div>`
      : `<div class="empty">No decisions yet. Click <b>Run all test scenarios</b> or submit a vendor.</div>`;

    const open = live.filter((r) => r.status === "PENDING").reverse().slice(0, 5);
    $("#attn").innerHTML = open.length ? open.map((r) => `<li data-id="${esc(r.id)}"><b>${esc(r.vendor_name)}</b>
        <span class="chip">${r.waiting_on === "vendor" ? "waiting on vendor" : "needs reviewer"}</span><span class="why">${esc(r.top_issue || "")}</span></li>`).join("")
      : `<li class="muted small" style="cursor:default">Nothing open — every case is decided.</li>`;
    const freq = {};
    data.runs.forEach((r) => (r.issues || []).forEach((i) => { freq[i.code] = (freq[i.code] || 0) + 1; }));
    const top = Object.entries(freq).sort((a, b) => b[1] - a[1]).slice(0, 7);
    const max = top[0]?.[1] || 1;
    $("#meters").innerHTML = top.length ? top.map(([c, n]) => `
      <div class="meter-row" title="${esc(ISSUE_LABEL[c] || c)}: ${n}"><div class="nm">${esc(ISSUE_LABEL[c] || c)}</div>
      <div class="meter-track"><div class="meter-fill" style="width:${(n / max) * 100}%"></div></div><div class="n">${n}</div></div>`).join("")
      : `<div class="empty">No issues recorded yet.</div>`;

    $$("#filters button").forEach((b) => b.classList.toggle("on", b.dataset.f === filter));
    const rows = data.runs.filter((r) => (filter === "all" || r.status === filter) &&
      (!q || `${r.vendor_name} ${r.country} ${r.id} ${country(r.country)}`.toLowerCase().includes(q)));
    $("#count").textContent = `${rows.length} of ${data.runs.length} runs`;
    $("#rows").innerHTML = rows.length ? rows.map((r) => {
      const next = r.status === "PENDING" ? (r.waiting_on === "vendor" ? "Waiting on vendor · " : "With reviewer · ") : "";
      const issue = r.status === "RUNNING" ? "Processing…" : r.status === "APPROVED" ? (r.reviewer ? "Approved by reviewer override" : "All checks passed") : (r.top_issue || "—");
      return `<tr class="click" data-id="${esc(r.id)}">
        <td class="vendor-cell"><b>${esc(r.vendor_name || "(no name)")}</b><span>${esc(country(r.country))} · <span class="mono">${esc(r.id)}</span></span></td>
        <td>${badge(r.status)} ${r.superseded_by ? `<span class="chip" title="A newer submission replaced this one">superseded</span>` : ""}${r.reviewer ? `<span class="chip">reviewed</span>` : ""}</td>
        <td class="mono">${r.risk_score ?? "—"}</td>
        <td class="issue" title="${esc(next + issue)}">${esc(next)}${esc(issue)}</td>
        <td><span class="chip">${esc((r.source || "").replace("sample:", "test: "))}</span>${r.previous_run_id ? ` <span class="chip" title="Resubmission of ${esc(r.previous_run_id)}">resubmission</span>` : ""}</td>
        <td class="muted small">${ago(r.created_at)}</td></tr>`;
    }).join("") : `<tr><td colspan="6" class="empty">No runs match.</td></tr>`;
  };

  const load = async () => { data = await api("/api/runs"); paint(); };
  await load();
  const timer = setInterval(() => { if (data.runs.some((r) => r.status === "RUNNING") || Date.now() < (window._seedUntil || 0)) load(); }, 1500);
  cleanup.push(() => clearInterval(timer));

  $("#filters").onclick = (e) => { const f = e.target.dataset.f; if (f) { filter = f; sessionStorage.setItem("dash-filter", f); paint(); } };
  $("#q").oninput = (e) => { q = e.target.value.toLowerCase().trim(); paint(); };
  $("#attn").onclick = (e) => { const li = e.target.closest("li[data-id]"); if (li) location.hash = `#/run/${li.dataset.id}`; };
  $("#rows").onclick = (e) => { const tr = e.target.closest("tr[data-id]"); if (tr) location.hash = `#/run/${tr.dataset.id}`; };
  $("#seed").onclick = async () => {
    try { const r = await api("/api/samples/run-all", { method: "POST" }); window._seedUntil = Date.now() + 20000; toast(`Running ${r.queued} test scenarios…`); load(); }
    catch (err) { toast(err.message); }
  };
  $("#reset").onclick = async () => { if (!confirm("Delete all runs, emails and non-seeded vendors?")) return; await api("/api/reset", { method: "POST" }); toast("Demo data reset"); load(); };
}

/* ---------------------------------------------------------------- new submission */
const SCHEME = { GB: "iban", DE: "iban", NL: "iban", FR: "iban", IE: "iban", AE: "iban", US: "aba", IN: "ifsc" };
const TAX_HINT = { US: "EIN, e.g. 12-3456789", GB: "VAT number, e.g. GB123456789", DE: "USt-IdNr, e.g. DE123456789", IN: "GSTIN, 15 characters" };

async function renderNew(_arg, params) {
  const files = {};  // slot -> File
  const slotNames = META.slots;
  view.innerHTML = `
    <div class="page-head"><div><h1>New vendor submission</h1><p>What a vendor fills in on the onboarding portal. Load a test scenario or enter your own.</p></div></div>
    <div class="card roadmap"><div class="roadmap-head"><span class="chip soon">Not yet added</span><h2>Planned verification features</h2></div>
      <p class="small muted" style="margin:6px 0 10px">Every submission already goes through automated checks: completeness, tax ID and bank number formats and check digits, consistency across documents, expiry and cover, and fraud cross-checks. The following are not built yet:</p>
      <ul class="roadmap-list">
        <li><b>Document verification with the issuer:</b> confirming that a tax certificate, bank letter or insurance certificate is genuine with the tax authority, company registry, bank or insurer. Today documents are checked for consistency, not authenticity.</li>
        <li><b>Bank account verification with the bank:</b> confirming the account exists and is held by this vendor (e.g. penny drop, Confirmation of Payee). Today: format and check digits, plus cross-checks against the bank letter and the vendor master.</li>
        <li><b>Email and mobile number OTP verification:</b> one-time codes proving the contact controls the email address and phone number given.</li>
      </ul></div>
    <div id="banner"></div>
    <details class="card scn-wrap" ${params.get("from") ? "" : "open"} style="margin-bottom:14px">
      <summary><div><h2>Test scenarios</h2><span class="muted small">Happy path + 4 designed edge cases. “Load” fills the form so you can inspect or tweak it first.</span></div><span class="chip">${META.scenarios.length}</span></summary>
      <div class="card-pad"><div class="scenarios">${META.scenarios.map((s) => `
        <div class="scn"><div class="top"><span class="chip">${esc(s.edge)}</span>${badge(s.expected)}</div>
          <h3>${esc(s.title)}</h3><p>${esc(s.description)}</p>
          <div class="row"><button class="btn sm" data-load="${esc(s.key)}">Load into form</button><button class="btn sm" data-docs="${esc(s.key)}" title="Attach only the PDFs, then try AI autofill">Docs only</button><button class="btn sm primary" data-run="${esc(s.key)}">${I.play}Run now</button></div></div>`).join("")}
      </div></div>
    </details>
    <details class="card scn-wrap" id="import-wrap" style="margin-bottom:14px">
      <summary><div><h2>Import vendors from JSON</h2><span class="muted small">Onboard one or many vendors at once from a <code>.json</code> file. Each vendor runs through the same checks as the form.</span></div><span class="chip">.json</span></summary>
      <div class="card-pad">
        <div class="import-grid">
          <label class="drop json-drop" id="json-drop"><input type="file" accept="application/json,.json" id="json-file">
            <div class="ic">${I.doc}</div><div><span class="req">Up to 25 vendors per file</span><b>Vendors file (.json)</b><span class="fname">Drop or click to choose a file</span></div></label>
          <div class="small muted import-help">
            <p style="margin:0 0 6px">Accepted shapes: one vendor object, a list of vendors, or <code>{"vendors": [ … ]}</code>. Field names match the form: <code>legal_name</code> (required), <code>country</code>, <code>address</code>, <code>contact_name</code>, <code>contact_email</code>, <code>contact_phone</code>, <code>tax_id</code>, <code>bank_name</code>, <code>account_holder</code>, <code>iban</code>, <code>bic</code>, <code>routing_number</code>, <code>account_number</code>, <code>ifsc</code>, and others.</p>
            <p style="margin:0 0 10px">Documents are optional: <code>"documents": [{"slot": "bank_letter", "filename": "letter.pdf", "content_base64": "…"}]</code>, with slot one of ${Object.keys(slotNames).map((k) => `<code>${k}</code>`).join(", ")}. Vendors run in file order, so later entries are cross-checked against earlier ones.</p>
            <a class="btn sm" href="/api/submissions/batch/example" download="vendors_example.json">${I.doc}Download example file</a>
          </div>
        </div>
        <div id="import-result"></div>
      </div>
    </details>
    <form class="card" id="form" autocomplete="off">
      <input type="hidden" name="previous_run_id"><input type="hidden" name="source" value="form">
      <div class="autofill-bar"><div class="ab-text">${I.spark}<div><b>Have your documents ready?</b> Upload them in section 5 and let AI fill in this form. Every value is copied from your documents and tagged with its source, so you can check it before submitting.</div></div><button type="button" class="btn ai-btn autofill-btn">${I.spark}Autofill from documents</button></div>
      <fieldset><legend class="sec"><span class="n">1</span>Company</legend><div class="form-grid">
        <label class="f">Legal company name *<input type="text" name="legal_name" placeholder="As registered"></label>
        <label class="f">Country of registration *<select name="country"><option value="">Select…</option>${Object.entries(META.countries).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></label>
        <label class="f full">Registered address *<input type="text" name="address"></label>
        <label class="f">Trading name <span class="hint">if you invoice under a different name</span><input type="text" name="trading_name"></label>
        <label class="f">Parent company <span class="hint">if payments go to a group entity</span><input type="text" name="parent_company"></label>
        <label class="f">Website<input type="text" name="website" placeholder="example.com"></label>
        <label class="f">Entity type<select name="entity_type"><option value="company">Company</option><option value="individual">Individual / sole trader</option></select></label>
      </div></fieldset>
      <fieldset><legend class="sec"><span class="n">2</span>Contact</legend><div class="form-grid">
        <label class="f">Contact name *<input type="text" name="contact_name"></label>
        <label class="f">Contact email *<input type="email" name="contact_email"><span class="devnote"><b> note:</b> email OTP verification is not yet added.</span></label>
        <label class="f">Contact phone *<input type="text" name="contact_phone"><span class="devnote"><b> note:</b> OTP verification for mobile numbers is not yet added (cant be done for free).</span></label>
      </div></fieldset>
      <fieldset><legend class="sec"><span class="n">3</span>Tax registration</legend><div class="form-grid">
        <label class="f">Tax ID * <span class="hint" id="tax-hint">Select a country first</span><input type="text" name="tax_id"></label>
      </div></fieldset>
      <fieldset><legend class="sec"><span class="n">4</span>Bank details</legend>
        <p class="devnote-block"><span class="devnote"><b> note:</b> verifying the account with the bank (penny drop / Confirmation of Payee) is not yet added. Bank details are checked for format, check digits and consistency with the bank letter.</span></p><div class="form-grid">
        <label class="f">Bank name *<input type="text" name="bank_name"></label>
        <label class="f">Account holder name<input type="text" name="account_holder"></label>
        <label class="f" data-scheme="iban">IBAN *<input type="text" name="iban"></label>
        <label class="f" data-scheme="iban">BIC / SWIFT *<input type="text" name="bic"></label>
        <label class="f" data-scheme="aba">ABA routing number *<input type="text" name="routing_number"></label>
        <label class="f" data-scheme="ifsc">IFSC code *<input type="text" name="ifsc"></label>
        <label class="f" data-scheme="aba ifsc">Account number *<input type="text" name="account_number"></label>
      </div></fieldset>
      <fieldset id="docs-section"><legend class="sec"><span class="n">5</span>Documents <span class="muted small" style="font-weight:400">PDF, max 10 MB each</span></legend>
        <p class="devnote-block"><span class="devnote"><b> note:</b> Bank/tax documents verification is not yet automated, currently docs are only read, identified and checked for consistency, expiry and coverage.</span></p>
        <div class="drops">${Object.entries(slotNames).map(([slot, name]) => `
          <label class="drop" data-slot="${slot}"><input type="file" accept="application/pdf,.pdf" data-slot="${slot}">
            <div class="ic">${I.doc}</div><div><span class="req">${META.required_docs.includes(slot) ? "Required" : "Recommended"}</span><b>${esc(name)}</b><span class="fname">Drop or click to upload</span></div></label>`).join("")}
        </div><div class="autofill-row"><button type="button" class="btn ai-btn autofill-btn">${I.spark}Autofill from documents</button><span class="muted small">Fills empty fields only; your own entries are never overwritten.</span></div></fieldset>
      <div class="form-foot"><span class="muted small">Submitting starts the automated checks; you'll watch each stage live.</span>
        <div class="actions"><button class="btn" type="button" id="clear">Clear</button><button class="btn primary" type="submit" id="submit">${I.play}Submit &amp; run checks</button></div></div>
    </form>`;

  const form = $("#form");
  const setFile = (slot, file) => {
    if (file) files[slot] = file; else delete files[slot];
    const drop = $(`.drop[data-slot="${slot}"]`);
    drop.classList.toggle("has", !!file);
    $(".fname", drop).textContent = file ? `${file.name} · ${Math.max(1, Math.round(file.size / 1024))} KB` : "Drop or click to upload";
    $(".ic", drop).innerHTML = file ? I.check : I.doc;
  };
  const syncCountry = () => {
    const c = form.country.value, sch = SCHEME[c];
    $$("[data-scheme]", form).forEach((el) => el.classList.toggle("hidden", !!sch && !el.dataset.scheme.split(" ").includes(sch)));
    $("#tax-hint").textContent = TAX_HINT[c] || (c ? "Format checked manually for this country" : "Select a country first");
  };
  const fill = (sub) => {
    for (const el of form.elements) if (el.name && el.name !== "source" && el.type !== "file") el.value = sub[el.name] ?? "";
    let c = sub.country || "";
    const alias = { "united kingdom": "GB", germany: "DE", india: "IN", "united states": "US", usa: "US", uk: "GB" };
    form.country.value = META.countries[c] ? c : (alias[c.toLowerCase()] || "");
    syncCountry();
  };
  const fetchFile = async (url, name) => { const b = await (await fetch(url)).blob(); return new File([b], name, { type: "application/pdf" }); };
  const loadScenario = async (key) => {
    const s = META.scenarios.find((x) => x.key === key);
    fill(s.submission);
    form.source.value = `sample:${key}`;
    Object.keys(slotNames).forEach((k) => setFile(k, null));
    for (const [slot, fn] of Object.entries(s.files)) setFile(slot, await fetchFile(`/api/samples/${key}/files/${fn}`, fn));
    $("#banner").innerHTML = `<div class="banner">${I.info}<span>Loaded <b>${esc(s.title)}</b> — expected outcome ${badge(s.expected)}. Edit anything you like, then submit.</span></div>`;
    form.scrollIntoView({ behavior: "smooth" });
  };

  const clearTags = () => {
    $$(".src-tag", form).forEach((t) => t.remove());
    $$("label.autofilled", form).forEach((l) => l.classList.remove("autofilled", "ai", "rule"));
  };
  const markFilled = (el, info) => {
    const label = el.closest("label");
    if (!label) return;
    label.classList.add("autofilled", info.source);
    label.insertAdjacentHTML("beforeend", `<span class="src-tag ${info.source}">${info.source === "ai" ? I.spark + "AI" : "RULE"} · from ${esc(info.from)}</span>`);
    el.addEventListener("input", () => { label.classList.remove("autofilled", "ai", "rule"); $(".src-tag", label)?.remove(); }, { once: true });
  };
  const runAutofill = async () => {
    if (!Object.keys(files).length) { toast("Attach at least one document in section 5 first"); $("#docs-section").scrollIntoView({ behavior: "smooth" }); return; }
    const btns = $$(".autofill-btn", form);
    btns.forEach((b) => { b.disabled = true; b.innerHTML = `${I.spin}Reading documents…`; });
    try {
      const fd = new FormData();
      for (const [slot, f] of Object.entries(files)) fd.append(slot, f, f.name);
      const res = await api("/api/autofill", { method: "POST", body: fd });
      clearTags();
      const filled = [], kept = [];
      for (const [name, info] of Object.entries(res.fields)) {
        const el = form.elements[name];
        if (!el) continue;
        const cur = (el.value || "").trim();
        if (cur && cur.toLowerCase() !== info.value.toLowerCase()) { kept.push([name, info]); continue; }
        if (cur) continue;
        if (el.tagName === "SELECT" && ![...el.options].some((o) => o.value === info.value)) continue;
        el.value = info.value; markFilled(el, info); filled.push(info);
      }
      syncCountry();
      const nAi = filled.filter((f) => f.source === "ai").length;
      const notes = [];
      for (const d of res.documents) {
        if (!d.readable) notes.push(`“${d.filename}” could not be read (scanned image?).`);
        else if (d.detected && d.detected !== d.slot) notes.push(`“${d.filename}” looks like a ${META.slots[d.detected]}, not a ${META.slots[d.slot]}; it will be re-filed automatically when you submit.`);
      }
      kept.forEach(([n, i]) => notes.push(`Kept your ${n.replace(/_/g, " ")}; the document says “${i.value}”.`));
      $("#banner").innerHTML = `<div class="banner ai">${I.spark}<div><b>Filled ${filled.length} field${filled.length === 1 ? "" : "s"} from ${res.documents.length} document${res.documents.length === 1 ? "" : "s"}</b>: ${filled.length - nAi} by rules, ${nAi} by AI${META.llm.enabled ? "" : " (AI assist is off, rules only)"}. Each value was copied from the document text. Please check them and complete the contact details.
        ${notes.length ? `<ul class="small" style="margin:6px 0 0;padding-left:18px">${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}</div></div>`;
      form.scrollIntoView({ behavior: "smooth" });
    } catch (err) { toast(err.message); }
    finally { btns.forEach((b) => { b.disabled = false; b.innerHTML = `${I.spark}Autofill from documents`; }); }
  };
  const loadDocsOnly = async (key) => {
    const s = META.scenarios.find((x) => x.key === key);
    form.reset(); clearTags(); form.previous_run_id.value = ""; form.source.value = `sample:${key}`;
    Object.keys(slotNames).forEach((k) => setFile(k, null));
    for (const [slot, fn] of Object.entries(s.files)) setFile(slot, await fetchFile(`/api/samples/${key}/files/${fn}`, fn));
    syncCountry();
    $("#banner").innerHTML = `<div class="banner ai">${I.spark}<span>Attached the documents for <b>${esc(s.title)}</b> with an empty form. Click <b>Autofill from documents</b> to let AI fill it in.</span></div>`;
    form.scrollIntoView({ behavior: "smooth" });
  };
  $$(".autofill-btn", form).forEach((b) => (b.onclick = runAutofill));
  form.country.onchange = syncCountry;
  $$(".drop input", form).forEach((inp) => {
    inp.onchange = () => setFile(inp.dataset.slot, inp.files[0]);
    const drop = inp.closest(".drop");
    drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
    drop.ondragleave = () => drop.classList.remove("over");
    drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); if (e.dataTransfer.files[0]) setFile(inp.dataset.slot, e.dataTransfer.files[0]); };
  });
  view.onclick = async (e) => {
    const l = e.target.closest("[data-load]"), r = e.target.closest("[data-run]"), dOnly = e.target.closest("[data-docs]");
    if (l) { clearTags(); await loadScenario(l.dataset.load); }
    if (dOnly) await loadDocsOnly(dOnly.dataset.docs);
    if (r) {
      r.disabled = true;
      try { const { run_id } = await api(`/api/samples/${r.dataset.run}/run`, { method: "POST" }); location.hash = `#/run/${run_id}`; }
      catch (err) { toast(err.message); r.disabled = false; }
    }
  };
  cleanup.push(() => { view.onclick = null; });

  const importJson = async (file) => {
    const out = $("#import-result"), drop = $("#json-drop");
    if (!file) return;
    $(".fname", drop).textContent = `${file.name} · ${Math.max(1, Math.round(file.size / 1024))} KB`;
    let body;
    try { body = JSON.parse(await file.text()); }
    catch (err) { out.innerHTML = `<div class="banner bad">${I.x}<span><b>${esc(file.name)}</b> is not valid JSON: ${esc(err.message)}</span></div>`; return; }
    out.innerHTML = `<div class="banner">${I.spin}<span>Importing…</span></div>`;
    const r = await fetch("/api/submissions/batch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    let res = {}; try { res = await r.json(); } catch {}
    if (!r.ok) {
      const d = res.detail, errs = (d && d.errors) || [];
      out.innerHTML = `<div class="banner bad">${I.x}<div><b>Nothing imported.</b> ${esc(typeof d === "string" ? d : (d && d.message) || r.statusText)}
        ${errs.length ? `<ul class="small" style="margin:6px 0 0;padding-left:18px">${errs.map((e) => `<li>Vendor ${e.index}${e.legal_name ? ` (${esc(e.legal_name)})` : ""}: ${esc(e.error)}</li>`).join("")}</ul>` : ""}</div></div>`;
      return;
    }
    window._seedUntil = Date.now() + 15000;
    const rows = res.accepted.map((a) => `<tr><td class="muted">${a.index}</td><td><b>${esc(a.legal_name)}</b>${a.warnings.map((w) => `<div class="small muted">${esc(w)}</div>`).join("")}</td>
        <td data-status="${a.run_id}">${badge("RUNNING")}</td><td><a class="btn sm" href="#/run/${a.run_id}">${I.play}Watch</a></td></tr>`).join("")
      + res.errors.map((e) => `<tr><td class="muted">${e.index}</td><td><b>${esc(e.legal_name || "(no name)")}</b><div class="small" style="color:var(--crit-ink)">${esc(e.error)}</div></td><td><span class="chip">Skipped</span></td><td></td></tr>`).join("");
    out.innerHTML = `<div class="banner">${I.info}<span>Imported <b>${res.accepted.length}</b> vendor${res.accepted.length === 1 ? "" : "s"}${res.errors.length ? `, skipped <b>${res.errors.length}</b>` : ""}. They run one after another; results also appear on the <a href="#/">Dashboard</a>.</span></div>
      <div class="table-wrap"><table class="t"><thead><tr><th>#</th><th>Vendor</th><th>Status</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`;
    const pending = new Set(res.accepted.map((a) => a.run_id));
    const poll = setInterval(async () => {
      if (!document.body.contains(out) || !pending.size) { clearInterval(poll); return; }
      for (const id of [...pending]) {
        try {
          const run = await api(`/api/runs/${id}`);
          if (run.status === "RUNNING") continue;
          pending.delete(id);
          const cell = $(`[data-status="${id}"]`, out);
          if (cell) cell.innerHTML = badge(run.status);
        } catch { pending.delete(id); }
      }
    }, 1500);
    cleanup.push(() => clearInterval(poll));
  };
  $("#json-file").onchange = (e) => { importJson(e.target.files[0]); e.target.value = ""; };
  {
    const drop = $("#json-drop");
    drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
    drop.ondragleave = () => drop.classList.remove("over");
    drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); importJson(e.dataTransfer.files[0]); };
  }
  $("#clear").onclick = () => { clearTags(); form.reset(); Object.keys(slotNames).forEach((k) => setFile(k, null)); $("#banner").innerHTML = ""; syncCountry(); };
  form.onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData();
    for (const el of form.elements) if (el.name && el.type !== "file") fd.append(el.name, el.value);
    for (const [slot, f] of Object.entries(files)) fd.append(slot, f, f.name);
    $("#submit").disabled = true;
    try { const { run_id } = await api("/api/submissions", { method: "POST", body: fd }); location.hash = `#/run/${run_id}`; }
    catch (err) { toast(err.message); $("#submit").disabled = false; }
  };
  syncCountry();

  const from = params.get("from");
  if (from) {
    const prev = await api(`/api/runs/${from}`);
    fill(prev.submission);
    form.previous_run_id.value = from;
    form.source.value = "resubmission";
    for (const d of prev.submission.documents || []) {
      try { setFile(d.slot, await fetchFile(`/api/runs/${from}/documents/${d.slot}`, d.filename)); } catch {}
    }
    const reqs = prev.result?.requests || [];
    $("#banner").innerHTML = `<div class="banner" style="align-items:flex-start">${I.reply}<div><b>Vendor reply to ${esc(from)}</b> — the previous answers and documents are pre-filled. Fix what was requested, then resubmit; changes are compared against the earlier run.
      ${reqs.length ? `<ol class="req-list" style="margin-top:8px">${reqs.map((r) => `<li>${esc(r)}</li>`).join("")}</ol>` : ""}</div></div>`;
  } else if (params.get("scenario")) {
    await loadScenario(params.get("scenario"));
  }
}

/* ---------------------------------------------------------------- live run view */
async function renderRun(id) {
  const run = await api(`/api/runs/${id}`);
  const s = run.submission;
  view.innerHTML = `
    <div class="page-head">
      <div><a href="#/dashboard" class="small">← Dashboard</a>
        <h1 style="margin-top:6px">${esc(s.legal_name || "(no name)")}</h1>
        <div class="run-meta"><span class="mono">${esc(run.id)}</span><span>${esc(country(run.country || s.country))}</span><span>${fmtTime(run.created_at)}</span>
          <span>${esc((run.source || "").replace("sample:", "test scenario: "))}</span>
          ${run.previous_run_id ? `<span>resubmission of <a href="#/run/${esc(run.previous_run_id)}">${esc(run.previous_run_id)}</a></span>` : ""}
          ${run.superseded_by ? `<span>superseded by <a href="#/run/${esc(run.superseded_by)}">${esc(run.superseded_by)}</a></span>` : ""}</div></div>
      <div id="head-badge">${badge(run.status, true)}</div>
    </div>
    <div class="run-grid">
      <div class="card"><div class="card-head"><h2>Pipeline</h2><span class="muted small" id="progress"></span></div>
        <ol class="timeline" id="timeline">${META.stages.map((st, i) => `
          <li class="stage queued" data-stage="${st.key}"><div class="node">${i + 1}</div>
            <div class="stage-body"><div class="stage-title"><h3>${esc(st.title)}</h3><span class="muted small ms"></span></div>
            <div class="stage-desc">${esc(st.desc)}</div><div class="stage-content"></div></div></li>`).join("")}
        </ol></div>
      <div class="run-side" id="side"><div class="card decision"><h2>Decision</h2><p class="muted" style="margin:8px 0 0">${I.spin.replace("<svg", '<svg width="14" height="14" style="vertical-align:-2px"')} Running checks…</p></div></div>
    </div>`;

  let doneStages = 0;
  const stageEl = (k) => $(`.stage[data-stage="${k}"]`);
  const apply = (ev) => {
    const el = stageEl(ev.stage);
    const box = el && $(".stage-content", el);
    if (ev.state === "start" && el) {
      el.className = "stage running"; $(".node", el).innerHTML = I.spin;
      $("#progress").textContent = `Stage ${META.stages.findIndex((x) => x.key === ev.stage) + 1} of ${META.stages.length}`;
    } else if (ev.state === "log" && box) {
      box.insertAdjacentHTML("beforeend", `<div class="log">${esc(ev.data.message)}</div>`);
    } else if (ev.state === "finding" && box) {
      box.insertAdjacentHTML("beforeend", findingHTML(ev.data));
    } else if (ev.state === "document" && box) {
      const d = ev.data, nm = META.slots[d.type] || d.type;
      box.insertAdjacentHTML("beforeend", `<div class="docrow">${I.doc.replace("<svg", '<svg width="15" height="15"')}<b>${esc(d.filename)}</b> → ${esc(nm)}
        <span class="chip ${d.classified_by === "llm" ? "llm" : ""}">${d.classified_by === "llm" ? "AI classified" : "rule classified"}</span>
        <span class="muted">${Object.keys(d.fields).filter((k) => !k.endsWith("_parsed")).length} fields extracted</span></div>`);
    } else if (ev.state === "done" && el) {
      const v = ev.data.verdict; el.className = `stage done ${v}`;
      $(".node", el).innerHTML = v === "pass" ? I.check : v === "warn" ? I.bang : I.x;
      $(".ms", el).textContent = `${ev.data.ms} ms`;
      doneStages++;
    } else if (ev.state === "complete") {
      $("#progress").textContent = `Completed · ${META.stages.length} stages`;
      finish();
    } else if (ev.state === "error") {
      $("#progress").textContent = "Failed";
      $("#side").innerHTML = `<div class="card decision"><h2>Pipeline error</h2><p class="reason">${esc(ev.data.message)}</p></div>`;
      $("#head-badge").innerHTML = badge("ERROR", true);
    } else if (ev.state === "review") {
      /* reviewer action replayed — shown in side panel */
    }
  };
  const finish = async () => { const full = await api(`/api/runs/${id}`); renderSide(full); $("#head-badge").innerHTML = badge(full.status, true); };

  const es = new EventSource(`/api/runs/${id}/stream`);
  es.onmessage = (m) => { const ev = JSON.parse(m.data); apply(ev); if (ev.state === "complete" || ev.state === "error") es.close(); };
  es.onerror = () => { es.close(); if (run.status !== "RUNNING") finish(); };
  cleanup.push(() => es.close());
  if (run.status === "ERROR") apply({ state: "error", data: { message: run.result?.error || "unknown error" } });
}

function renderSide(run) {
  const r = run.result || {}, s = run.submission, rv = run.reviewer;
  const riskColor = r.risk_score >= 75 ? "var(--crit)" : r.risk_score >= 25 ? "var(--review)" : r.risk_score > 0 ? "var(--warn)" : "var(--good)";
  const waiting = r.status === "PENDING" && !rv ? `<div class="chip" style="margin-top:10px">${I.clock.replace("<svg", '<svg width="12" height="12"')} Waiting on ${esc(r.waiting_on)}</div>` : "";
  const counts = r.counts || {};
  const docs = Object.entries(r.documents || {});
  const findings = r.findings || [];
  $("#side").innerHTML = `
    <div class="card decision">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px"><h2>Decision</h2>${badge(run.status, true)}</div>
      <p class="reason">${esc(r.reason)}</p>
      ${rv ? `<div class="finding ${rv.action === "approve" ? "pass" : "critical"}" style="margin-top:10px"><div class="ft">${rv.action === "approve" ? I.okc : I.stop}<span>Reviewer ${rv.action === "approve" ? "approved" : "rejected"} — machine said ${esc(rv.machine_status)}</span></div><div class="fd">“${esc(rv.note)}” — ${esc(rv.by)}, ${fmtTime(rv.at)}${rv.vendor_id ? ` · vendor ${esc(rv.vendor_id)}` : ""}</div></div>` : ""}
      ${waiting}
      <div class="risk"><div class="risk-head"><span>Risk score</span><b>${r.risk_score}/100</b></div>
        <div class="risk-track"><div class="risk-fill" style="width:${Math.max(2, r.risk_score)}%;background:${riskColor}"></div><div class="risk-thr" style="left:75%"><span>reject ≥ 75</span></div></div></div>
      <div class="legend" style="margin-top:22px">${["pass", "info", "action", "review", "critical"].map((k) => `<span class="small">${SEV_ICON[k].replace("<svg", '<svg width="13" height="13"')} ${SEV_LABEL[k]} <b>${counts[k] || 0}</b></span>`).join("")}</div>
      ${r.vendor_id ? `<p class="small" style="margin:12px 0 0">${I.check.replace("<svg", '<svg width="13" height="13" style="color:var(--good-ink);vertical-align:-2px"')} Created in vendor master as <b>${esc(r.vendor_id)}</b></p>` : ""}
      ${r.resolved?.length ? `<div style="margin-top:12px"><h3 class="small">Resolved since last submission</h3><ul class="resolved">${r.resolved.map((x) => `<li>${I.check}${esc(x)}</li>`).join("")}</ul></div>` : ""}
      <div class="actions" style="margin-top:14px">
        ${run.status === "PENDING" && !run.superseded_by ? `<a class="btn sm" href="#/new?from=${esc(run.id)}">${I.reply}Simulate vendor reply</a>` : ""}
        ${run.superseded_by ? `<a class="btn sm" href="#/run/${esc(run.superseded_by)}">Open newer submission →</a>` : ""}
      </div>
    </div>
    <div class="card">
      <div class="tabs" id="tabs">
        <button data-t="email" class="on">Vendor email</button><button data-t="ask" class="ask-tab">${I.spark}Ask AI</button><button data-t="summary">Reviewer brief</button>
        <button data-t="docs">Documents (${docs.length})</button>${run.status === "PENDING" && !run.superseded_by ? `<button data-t="review">Review</button>` : ""}
      </div>
      <div id="tab-body"></div>
    </div>`;

  const e = r.email || {};
  const aiNotes = findings.filter((f) => f.code === AI_NOTE);
  const titleOf = {};
  findings.forEach((f) => { if (!titleOf[f.code]) titleOf[f.code] = f; });
  const chat = [];
  const suggestions = [
    `Why is this case ${String(run.status).toLowerCase()}?`,
    ...(run.status === "PENDING" ? ["What exactly do we need from the vendor?"] : []),
    ...(run.previous_run_id ? ["What changed since the last submission?"] : []),
    ...(aiNotes.length ? ["Explain the AI observations"] : []),
    "What should I verify before approving?",
  ].slice(0, 4);
  const chatHTML = () => chat.map((m) => `
      <div class="msg q">${esc(m.q)}</div>
      <div class="msg a ${m.error ? "err" : ""}">${m.a == null ? `${I.spin} Thinking…` : esc(m.a)}
        ${m.cites?.length ? `<div class="cites">${m.cites.map((c) => `<span class="cite ${esc(titleOf[c]?.severity || "info")}" title="${esc(c)}">${esc(titleOf[c]?.title || c)}</span>`).join("")}</div>` : ""}</div>`).join("");
  const askTab = () => META.llm.enabled ? `<div class="tab-body ask">
        <p class="small muted" style="margin:0 0 10px">${I.spark.replace("<svg", '<svg width="13" height="13" style="vertical-align:-2px;color:var(--accent)"')} Answers come only from this case's findings and documents (bank numbers masked) and cite the findings used. The AI can explain the decision but cannot change it.</p>
        <div class="chat" id="chat">${chatHTML()}</div>
        <div class="suggest">${suggestions.map((q) => `<button type="button" class="chip" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>
        <form id="ask-form" class="ask-form"><input type="text" id="ask-q" placeholder="Ask anything about this case…" maxlength="500" autocomplete="off"><button class="btn primary sm" type="submit">${I.send}Ask</button></form></div>`
    : `<div class="tab-body"><p class="muted">AI assist is off. Set LLM_API_KEY, LLM_BASE_URL and LLM_MODEL in .env to enable it.</p></div>`;
  const ask = async (q) => {
    q = (q || "").trim();
    if (!q || chat.some((m) => m.a == null)) return;
    const history = chat.filter((m) => m.a && !m.error).slice(-4).map((m) => ({ q: m.q, a: m.a }));
    const m = { q, a: null }; chat.push(m); $("#chat").innerHTML = chatHTML(); $("#chat").scrollTop = 1e6;
    try { const out = await api(`/api/runs/${run.id}/ask`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q, history }) }); m.a = out.answer; m.cites = out.cites; }
    catch (err) { m.a = err.message; m.error = true; }
    if ($("#chat")) { $("#chat").innerHTML = chatHTML(); $("#chat").scrollTop = 1e6; }
  };
  const tabs = {
    ask: askTab,
    email: () => `<div class="email"><div class="hdr"><b>To</b><span>${esc(e.to || "—")}</span><b>Subject</b><span>${esc(e.subject)}</span>
        <b>Wording</b><span>${e.llm ? `<span class="chip llm">AI-worded · ${esc(r.llm_model)}</span>` : `<span class="chip">template</span>`} <span class="muted small">requested items are always inserted by rules</span></span></div>
        ${e.routing_note ? `<div class="banner" style="margin:12px 18px 0">${I.warn}<span>${esc(e.routing_note)}</span></div>` : ""}<pre>${esc(e.body)}</pre></div>`,
    summary: () => `<div class="tab-body"><p style="margin:0 0 10px">${esc(r.reviewer_summary?.text)}</p>
        <div class="small muted">${r.reviewer_summary?.llm ? "Written by AI from the findings below; it cannot change the decision." : "Generated from a template (AI assist off)."}</div>
        <h3 style="margin:16px 0 8px">Open items</h3>
        ${findings.filter((f) => ["critical", "review", "action"].includes(f.severity)).map((f) => findingHTML(f, "margin-bottom:6px")).join("") || `<p class="muted small">None.</p>`}
        <h3 style="margin:16px 0 8px">AI second look <span class="muted small" style="font-weight:400">notes only, never affect the decision</span></h3>
        ${aiNotes.length ? aiNotes.map((f) => findingHTML(f, "margin-bottom:6px")).join("") : `<p class="muted small">${META.llm.enabled ? "AI found nothing beyond what the rules already checked." : "AI assist is off."}</p>`}
        ${r.llm_used?.length ? `<h3 style="margin:16px 0 6px">Where AI was used</h3><ul class="small" style="margin:0;padding-left:18px">${r.llm_used.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p class="small muted" style="margin-top:14px">No AI was used in this run; every value came from deterministic extraction.</p>`}</div>`,
    docs: () => `<div class="tab-body">${docs.length ? docs.map(([t, d]) => `
        <div class="doc-card"><div class="dh"><div><b>${esc(META.slots[t] || t)}</b><div class="small muted">${esc(d.filename)}${d.slot !== t ? ` · uploaded as ${esc(META.slots[d.slot] || d.slot)}` : ""}</div></div>
          <a class="btn sm" target="_blank" href="/api/runs/${esc(run.id)}/documents/${esc(d.slot)}">${I.eye}View PDF</a></div>
          <dl class="kv">${Object.entries(d.fields).filter(([k]) => !k.endsWith("_parsed") && k !== "coverage_amount" && k !== "coverage_currency").map(([k, v]) => `
            <dt>${esc(k.replace(/_/g, " ").replace("raw", ""))}</dt><dd>${esc(v)}<span class="src ${d.field_source?.[k] === "llm" ? "llm" : "regex"}">${d.field_source?.[k] === "llm" ? "AI" : "RULE"}</span></dd>`).join("")}</dl></div>`).join("")
        : `<p class="muted">No documents could be identified.</p>`}</div>`,
    review: () => `<div class="tab-body review-box"><p class="small" style="margin:0">Resolve this case manually. Your decision and note are stored next to the machine's findings in the audit trail.</p>
        <textarea id="note" placeholder="Reason, e.g. 'Called Jonas Weber on the number from Companies House — parent company payment confirmed.'"></textarea>
        <div class="actions"><button class="btn good" data-act="approve">${I.check}Approve vendor</button><button class="btn danger" data-act="reject">${I.x}Reject</button></div></div>`,
  };
  const show = (t) => { $$("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.t === t)); $("#tab-body").innerHTML = tabs[t](); };
  $("#tabs").onclick = (ev) => { const t = ev.target.dataset.t; if (t) show(t); };
  $("#tab-body").onsubmit = (ev) => { if (ev.target.id === "ask-form") { ev.preventDefault(); const i = $("#ask-q"); ask(i.value); i.value = ""; } };
  $("#tab-body").onclick = async (ev) => {
    const sq = ev.target.closest("[data-q]");
    if (sq) { ask(sq.dataset.q); return; }
    const act = ev.target.closest("[data-act]")?.dataset.act;
    if (!act) return;
    try {
      await api(`/api/runs/${run.id}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: act, note: $("#note").value }) });
      toast(`Vendor ${act === "approve" ? "approved" : "rejected"} by reviewer`);
      const full = await api(`/api/runs/${run.id}`); renderSide(full); $("#head-badge").innerHTML = badge(full.status, true);
    } catch (err) { toast(err.message); }
  };
  show("email");
}

/* ---------------------------------------------------------------- vendor master / outbox */
async function renderVendors() {
  const { vendors } = await api("/api/vendors");
  view.innerHTML = `<div class="page-head"><div><h1>Vendor master</h1><p>Approved vendors that can be paid. New submissions are screened against this list for shared bank accounts and duplicate tax IDs.</p></div></div>
    <div class="card"><div class="table-wrap"><table class="t"><thead><tr><th>ID</th><th>Vendor</th><th>Country</th><th>Tax ID</th><th>Bank account</th><th>Approved</th><th>Origin</th></tr></thead><tbody>
    ${vendors.map((v) => `<tr><td class="mono">${esc(v.id)}</td><td><b>${esc(v.legal_name)}</b><div class="small muted">${esc(v.contact_email || "")}</div></td><td>${esc(country(v.country))}</td>
      <td class="mono">${esc(v.tax_id || "—")}</td><td class="mono">${esc(v.account_masked || "—")}</td><td class="small">${fmtTime(v.approved_at)}</td>
      <td>${v.run_id ? `<a href="#/run/${esc(v.run_id)}" class="mono">${esc(v.run_id)}</a>` : `<span class="chip">pre-existing</span>`}</td></tr>`).join("")}
    </tbody></table></div></div>`;
}

async function renderOutbox() {
  const { emails } = await api("/api/outbox");
  view.innerHTML = `<div class="page-head"><div><h1>Vendor emails</h1><p>Every message the process queued for vendors. In production this outbox is sent via your mail provider; here it is stored for review.</p></div></div>
    ${emails.length ? emails.map((m) => `<div class="card email" style="margin-bottom:12px"><div class="hdr"><b>To</b><span>${esc(m.to_addr)}</span><b>Subject</b><span><b style="color:var(--ink)">${esc(m.subject)}</b></span><b>Run</b><span><a class="mono" href="#/run/${esc(m.run_id)}">${esc(m.run_id)}</a> · ${fmtTime(m.created_at)}</span></div><pre>${esc(m.body)}</pre></div>`).join("")
      : `<div class="card empty">No emails yet.</div>`}`;
}

/* ---------------------------------------------------------------- how it works */
function renderHow() {
  const steps = [
    ["Read the submission", "Cleans up what the vendor typed and notices if this is a second attempt from the same company."],
    ["Check nothing is missing", "Each country needs different things — an IBAN in Germany, a routing number in the US, an IFSC code in India."],
    ["Read every document", "Opens each PDF, works out what it actually is (even if uploaded in the wrong box) and pulls out names, numbers and dates."],
    ["Verify the tax ID", "Every country's tax number has a built-in check digit. A failed check next to a valid certificate means a typo; a valid number from another country means something else."],
    ["Verify the bank account", "Validates the account number and asks the key question: is the account actually held by this company?"],
    ["Check documents are valid", "Right company, not expired, enough insurance cover, bank letter recent."],
    ["Look across everything", "Is this bank account already paying another vendor? Did the bank details change on a resubmission when nobody asked? Did the contact move to a gmail address?"],
    ["Decide", "Fixed rules, no guesswork: any critical issue → rejected; several red flags together → rejected; anything fixable → pending; otherwise approved."],
    ["Tell the vendor", "A plain-English email listing exactly what is needed — and nothing about fraud rules when fraud is suspected."],
  ];
  const sev = [["pass", "Check passed"], ["info", "Noted, doesn't block"], ["action", "Vendor must fix → pending"], ["review", "A person should look → pending"], ["critical", "Stop → rejected"]];
  view.innerHTML = `<div class="page-head"><div><h1>How it works</h1><p>A brief on the application: what the process checks & how it decides.</p></div><a class="btn primary" href="#/new">${I.play}Try it</a></div>
    <div class="card card-pad prose" style="margin-bottom:14px;max-width:none">
      <h2>Workflow</h2><p style="margin:6px 0 0">A vendor submits a form and their documents; in a few seconds the process checks completeness, validity and consistency the way a careful analyst would, then <b>approves</b>, <b>asks the vendor for exactly what is missing</b>, or <b>stops</b> a suspicious submission — and shows its reasoning for every step.</p></div>
    <div class="how" style="margin-bottom:14px">${steps.map(([t, d], i) => `<div class="card"><div class="num">STEP ${i + 1}</div><h3 style="margin-top:4px">${esc(t)}</h3><p>${esc(d)}</p></div>`).join("")}</div>
    <div class="grid-2">
      <div class="card card-pad"><h2>How findings turn into a decision</h2><div class="sev-legend" style="margin-top:12px">${sev.map(([k, d]) => `<div class="finding ${k}"><div class="ft">${SEV_ICON[k]}<span>${SEV_LABEL[k]}</span></div><div class="fd" style="margin-left:0">${d}</div></div>`).join("")}</div>
        <p class="small muted" style="margin-top:12px">Each finding also adds to a 0–100 risk score (fixable item 10, review flag 25–50, critical 100). A score of 75 or more is rejected even without a single critical issue — several moderate red flags together are treated as one serious one.</p></div>
      <div class="card card-pad"><h2>Where AI is — and isn't — used</h2>
        <p class="small" style="margin-top:8px"><b>AI helps with reading and explaining:</b> filling in the form from the vendor's documents, pulling fields out of messy documents the rules can't parse, a "second look" that notes inconsistencies the rules don't cover, a chat that answers a reviewer's questions about a case, and wording the email and reviewer brief. Every value or note must be backed by text that actually appears in the documents, and is labelled "AI".</p>
        <p class="small"><b>AI never decides.</b> Check-digit maths, name matching, expiry dates, the fraud screen and the final status are all fixed rules, so the same submission always gets the same answer and every decision can be explained to an auditor.</p>
        <p class="small muted">If the AI service is unavailable, every step still runs on rules alone.</p></div>
    </div>`;
}

/* ---------------------------------------------------------------- boot */
(async function boot() {
  const saved = (() => { try { return localStorage.getItem("theme"); } catch { return null; } })();
  if (saved) document.documentElement.dataset.theme = saved;
  $("#theme-btn").onclick = () => {
    const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", document.documentElement.dataset.theme); } catch {}
  };
  META = await api("/api/meta");
  const pill = $("#ai-pill");
  pill.innerHTML = META.llm.enabled ? `<i class="dot on"></i>AI assist: ${esc(META.llm.model)}` : `<i class="dot"></i>AI assist off · rules only`;
  pill.title = META.llm.enabled ? `OpenAI-compatible endpoint ${META.llm.base_url}` : "Set LLM_API_KEY, LLM_BASE_URL and LLM_MODEL in .env to enable";
  route();
})();
