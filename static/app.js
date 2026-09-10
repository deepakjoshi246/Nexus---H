const state = { cases: [], scenarios: [], selected: null };
let installPrompt = null;
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));

async function api(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Request failed.");
  return data;
}

function showToast(message) {
  const toast = $("#toast"); toast.textContent = message; toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 3200);
}

function renderCases() {
  const query = ($("#case-search").value || "").toLowerCase();
  const rows = state.cases.filter((item) => `${item.case_id} ${item.title || item.issue_type} ${item.customer_name}`.toLowerCase().includes(query));
  $("#case-count").textContent = state.cases.length;
  $("#case-list").innerHTML = rows.length ? rows.map((item) => `<div class="case-row ${state.selected?.case_id === item.case_id ? "selected" : ""}" data-case="${esc(item.case_id)}"><div class="case-row-top"><strong>${esc(item.case_id)}</strong><span class="priority ${(item.priority || "").toLowerCase()}">${esc(item.priority || "NORMAL")}</span></div><p>${esc(item.title || item.issue_type || "Unclassified case")}</p><p>${esc(item.customer_name || "Synthetic customer")}</p></div>`).join("") : '<div class="loading">No matching cases.</div>';
}

function renderScenarios() {
  $("#scenario-list").innerHTML = state.scenarios.map((item) => `<button class="scenario-btn" data-scenario="${esc(item.case_id || item.id)}">${esc(item.name || item.title || item.label)}</button>`).join("");
}

function renderConversation(messages = []) {
  $("#conversation-body").innerHTML = messages.length ? messages.map((message) => `<div class="message ${message.role === "agent" ? "agent" : ""}"><span class="avatar">${message.role === "agent" ? "N" : "C"}</span><div style="flex:1"><div class="message-meta"><strong>${message.role === "agent" ? "NEXUS-H" : esc(message.author || "Customer")}</strong><span>${esc(message.timestamp || "")}</span></div><p>${esc(message.content || message.text)}</p></div></div>`).join("") : '<div class="loading">No conversation supplied.</div>';
}

function renderCase(item) {
  state.selected = item;
  $("#empty-state").classList.add("hidden"); $("#active-case").classList.remove("hidden");
  $("#case-id").textContent = item.case_id; $("#case-title").textContent = item.title || item.issue_type || "Active case";
  $("#case-meta").textContent = `${item.customer_name || "Synthetic customer"} · ${item.priority || "NORMAL"} priority`;
  $("#case-status").textContent = item.status || "READY FOR ANALYSIS"; renderConversation(item.messages || item.conversation || []);
  $("#decision-card").innerHTML = '<span class="eyebrow">04 / AUTONOMY GATE</span><div class="decision-placeholder">Decision appears here after analysis.</div>';
  $("#signals-card").classList.add("hidden"); $("#brief-card").classList.add("hidden"); $("#activity-body").innerHTML = '<div class="activity-placeholder">Run analysis to see the agent retrieve only the context this case needs.</div>'; $("#audit-body").innerHTML = '<div class="loading">Run analysis to populate the audit timeline.</div>'; $("#analyze-btn").disabled = false; renderCases();
}

function evidenceChips(ids = []) { return ids.length ? `<div class="evidence-chips">${ids.map((id) => `<span class="chip">${esc(id)}</span>`).join("")}</div>` : ""; }

function renderAnalysis(result) {
  const decision = result.decision || result.autonomy_decision || {};
  const name = typeof decision === "string" ? decision : decision.decision;
  const normalized = String(name || "HANDOFF").toLowerCase();
  const reason = decision.reason || decision.why_stopped || result.escalation_reason || (decision.reason_codes || []).join(" · ") || "Decision based on retrieved case context.";
  const route = decision.recommended_destination || decision.destination || result.routing?.destination || "Human review";
  const highlights = decision.stop_reasons || [];
  const risk = decision.risk_level || (normalized === "handoff" ? "HIGH" : normalized === "approval" ? "MEDIUM" : "LOW");
  const confidence = Math.round((decision.confidence || result.brief?.confidence || 0) * 100);
  $("#decision-card").innerHTML = `<span class="eyebrow">04 / AUTONOMY GATE</span><div class="decision-state ${normalized}">${esc(name || "HANDOFF")}${normalized === "handoff" ? " REQUIRED" : ""}</div><div class="decision-reason"><strong>Why NEXUS-H stopped</strong>${highlights.length ? `<ul>${highlights.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : esc(reason)}</div><div class="decision-metrics"><span>RISK<strong>${esc(risk)}</strong></span><span>CONFIDENCE<strong>${confidence}%</strong></span></div><div class="decision-route">SELECTED ROUTE<strong>${esc(route)}</strong></div>`;
  const signals = result.signals || {};
  const signalEntries = Object.entries(signals);
  $("#signals-card").classList.remove("hidden"); $("#signals-body").innerHTML = signalEntries.length ? signalEntries.map(([key, value]) => { const score = typeof value === "number" ? value : value.score || 0; return `<div class="signal"><div class="signal-top"><span>${esc(key.replaceAll("_", " "))}</span><span>${Math.round(score * 100)}%</span></div><div class="signal-reason">${esc(value.reason || "")}</div><div class="bar"><i style="width:${Math.max(0, Math.min(100, score * 100))}%"></i></div></div>`; }).join("") : '<div class="loading">No signal detail returned.</div>';
  const brief = result.brief || result.human_brief;
  if (brief) { $("#brief-card").classList.remove("hidden"); $("#brief-body").innerHTML = [["CUSTOMER GOAL", brief.customer_goal], ["SUMMARY", brief.one_line_summary || brief.summary], ["ACTIONS ALREADY TAKEN", brief.actions_already_taken], ["WHY AI STOPPED", brief.escalation_reason], ["EVIDENCE GATHERED", brief.evidence_summary], ["NEXT ACTION", brief.recommended_next_step || brief.next_action], ["ROUTING RATIONALE", brief.routing_reason]].filter(([, value]) => value).map(([label, value]) => `<div class="brief-section"><label>${label}</label>${Array.isArray(value) ? `<ul>${value.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : `<p>${esc(value)}</p>`}</div>`).join(""); }
  const activity = result.tool_calls || result.activities || result.evidence || [];
  $("#tool-count").textContent = `${activity.length} TOOL CALLS`; $("#activity-body").innerHTML = activity.length ? activity.map((item) => `<div class="activity-item"><span class="activity-icon">✓</span><div><strong>${esc(item.tool || item.name || item.source || "Evidence retrieved")}</strong><p>${esc(item.summary || item.explanation || item.output || item.value || "Retrieved from synthetic source.")}</p>${evidenceChips(item.evidence_ids || [])}</div></div>`).join("") : '<div class="activity-placeholder">Decision completed with deterministic case evidence.</div>';
  const audit = result.audit || result.audit_events || [];
  $("#audit-body").innerHTML = audit.length ? audit.map((event) => `<div class="audit-event"><time>${esc(event.timestamp || "")}</time><div><strong>${esc(event.action || event.event_type || "EVENT")}</strong><p>${esc(event.reason || event.output_summary || "")}</p></div></div>`).join("") : '<div class="loading">No audit events returned.</div>';
}

async function analyze() {
  if (!state.selected) return;
  const button = $("#analyze-btn"); button.disabled = true; button.textContent = "Agent is retrieving…";
  try { const result = await api(`/api/cases/${encodeURIComponent(state.selected.case_id)}/analyze`, { method: "POST" }); renderAnalysis(result); await loadQueue(); showToast("Analysis complete — decision recorded."); }
  catch (error) { showToast(error.message); } finally { button.disabled = false; button.innerHTML = 'Run agent analysis <span>↗</span>'; }
}

async function loadQueue() {
  const data = await api("/api/queue"); const items = data.items || data.handoffs || data;
  $("#queue-count").textContent = items.length; $("#queue-body").innerHTML = items.length ? items.map((item) => `<tr><td><span class="priority ${(item.priority || "").toLowerCase()}">${esc(item.priority || "HIGH")}</span></td><td><strong>${esc(item.case_id)}</strong></td><td class="route">${esc(item.destination || item.team || "Human review")}</td><td class="reason-cell">${esc(item.escalation_reason || item.reason || "Requires specialist review")}</td><td>${esc(item.age || "now")}</td></tr>`).join("") : '<tr><td colspan="5" class="loading">No active handoffs.</td></tr>';
}

async function loadAll() {
  try { const [cases, scenarios] = await Promise.all([api("/api/cases"), api("/api/scenarios")]); state.cases = cases.items || cases.cases || cases; state.scenarios = scenarios.items || scenarios.scenarios || scenarios; renderCases(); renderScenarios(); await loadQueue(); if (state.cases[0]) renderCase(state.cases[0]); }
  catch (error) { showToast(error.message); $("#case-list").innerHTML = `<div class="loading">${esc(error.message)}</div>`; }
}

$("#case-list").addEventListener("click", (event) => { const row = event.target.closest("[data-case]"); if (row) renderCase(state.cases.find((item) => item.case_id === row.dataset.case)); });
$("#scenario-list").addEventListener("click", (event) => { const button = event.target.closest("[data-scenario]"); const item = state.cases.find((candidate) => candidate.case_id === button?.dataset.scenario || candidate.id === button?.dataset.scenario || candidate.scenario === button?.dataset.scenario); if (item) renderCase(item); });
$("#case-search").addEventListener("input", renderCases); $("#analyze-btn").addEventListener("click", analyze);
window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  installPrompt = event;
});
$("#install-btn").addEventListener("click", async () => {
  if (window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone) {
    showToast("NEXUS-H is already installed.");
    return;
  }
  if (installPrompt) {
    installPrompt.prompt();
    const result = await installPrompt.userChoice;
    if (result.outcome === "accepted") showToast("NEXUS-H was added to your apps.");
    installPrompt = null;
    return;
  }
  const isIos = /iphone|ipad|ipod/i.test(window.navigator.userAgent);
  showToast(isIos ? "Tap Share, then Add to Home Screen." : "Use your browser menu and choose Install app or Add to Home screen.");
});
setInterval(() => { $("#clock").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }, 1000);
loadAll();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/static/service-worker.js"));
}
