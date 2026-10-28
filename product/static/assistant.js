"use strict";
const A = {chat: null, chats: [], draft: "", folder: "", biFolder: "", busy: false, polling: false, error: ""};
const dataToolLabels = {reconcile_review: "Reconcile and review", list_files: "Find tables", inspect_table: "Read table", profile_table: "Check data quality", completion_check: "Check requested outputs", limit_rows: "Select row range", rename_columns: "Rename columns",
  select_columns: "Select columns", filter_rows: "Filter rows", sort_rows: "Sort rows", deduplicate: "Check duplicates",
  fill_missing: "Fill missing values", normalize_text: "Clean text", concatenate: "Append tables", join_tables: "Join tables",
  aggregate: "Group and calculate", derive_column: "Calculate a column", create_chart: "Create chart", export_report: "Create Excel report"};

function folderInput(id, label, value, action, required = false, disabled = false) {
  return `<div class="field"><label for="${id}">${label}</label><div class="folder-select"><input id="${id}" class="input" maxlength="4096" ${required ? "required" : ""} ${disabled ? "disabled" : ""} value="${esc(value || "")}"><button class="btn secondary" type="button" aria-label="Browse ${esc(label.replace(' (optional)', ''))}" data-action="${action}" ${disabled ? "disabled" : ""}>Browse…</button></div></div>`;
}
function folderLocations(folder, biFolder, files = []) {
  return `<div class="folder-locations"><div><strong>Input folder</strong><span>${esc(folder)}</span>${files.length ? `<span class="pill">${files.filter(file => file.group !== "bi").length} files</span>` : ""}</div>${biFolder ? `<div><strong>BI system folder</strong><span>${esc(biFolder)}</span>${files.length ? `<span class="pill">${files.filter(file => file.group === "bi").length} files</span>` : ""}</div>` : ""}</div>`;
}
function assistantEntry() {
  return `<section class="card data-entry"><div class="card-head"><h2>What would you like to do with your data?</h2></div><form id="assistant-form" class="card-body"><label for="assistant-request">Your request</label><textarea id="assistant-request" class="input command-input" required minlength="3" maxlength="3000" ${A.busy ? "disabled" : ""} placeholder="Process the input files and compare them with the BI reference data.">${esc(A.draft)}</textarea><div class="input-folders">${folderInput("assistant-folder", "Input folder", A.folder, "assistant-pick", true, A.busy)}${folderInput("assistant-bi-folder", "BI system folder (optional)", A.biFolder, "assistant-pick-bi", false, A.busy)}</div><div class="data-send"><button class="btn primary" type="submit" ${A.busy ? "disabled" : ""}>${A.busy ? "Opening…" : "Start task"} ${svg("arrow")}</button></div>${A.error ? `<p class="error-text" role="alert">${esc(A.error)}</p>` : ""}</form></section>`;
}

function assistantPage() {
  const chat = A.chat, active = chat?.active_turn;
  const actions = `<div class="flex"><select id="assistant-history" aria-label="Open conversation"><option value="">Conversations</option>${A.chats.map(item => `<option value="${item.id}" ${item.id === chat?.id ? "selected" : ""}>${esc(item.title)} · ${item.id}</option>`).join("")}</select><button class="btn secondary" data-action="assistant-new">${svg("plus")}New conversation</button></div>`;
  if (!chat) return `${heading("Data assistant", "", actions)}${assistantEntry()}`;
  return `${heading("Data assistant", "", actions)}${folderLocations(chat.folder, chat.bi_folder, chat.files)}<section class="data-conversation" aria-label="Conversation">${chat.turns.map(turn => `<article class="data-turn"><div class="data-user"><span class="data-speaker">You</span><div>${esc(turn.instruction)}</div></div><div class="data-response"><span class="data-speaker">Finance Flow</span>${turn.steps?.length ? `<details class="data-steps" ${turn.status === "running" ? "open" : ""}><summary>${turn.steps.length} steps</summary>${turn.steps.map(step => `<div class="data-step ${step.status === "error" ? "data-step-error" : ""}"><span>${svg(step.status === "error" ? "alert" : "check")}${esc(dataToolLabels[step.tool] || step.tool)}</span>${step.error ? `<p>${esc(step.error)}</p>` : step.result?.rows !== undefined ? `<span>${step.result.rows} rows${step.result.frame_id ? " · " + esc(step.result.frame_id) : ""}</span>` : ""}</div>`).join("")}</details>` : ""}${turn.status === "running" ? `<div class="data-working"><span class="busy"></span>Working locally<button class="btn ghost" data-action="assistant-cancel" data-turn="${turn.id}">Stop</button></div>` : ""}${turn.message ? `<div class="data-answer">${esc(turn.message)}</div>` : ""}${turn.error ? `<p class="error-text" role="alert">${esc(turn.error)}</p>` : ""}${assistantReviewCard(turn, Boolean(active))}${turn.status === "failed" && !turn.error ? '<p class="error-text">This request was interrupted. Saved results are available.</p>' : ""}${(turn.can_retry ?? ["failed", "cancelled"].includes(turn.status)) ? `<div class="data-send"><button class="btn secondary" data-action="assistant-retry" data-turn="${turn.id}" ${active || A.busy ? "disabled" : ""}>${svg("refresh")}Retry request</button></div>` : ""}</div></article>`).join("")}</section>${chat.preview ? assistantTable(chat.preview) : ""}${chat.charts.length ? `<section class="data-chart-grid">${chat.charts.map(chart => `<article class="card card-body"><h3>${esc(chart.title)}</h3>${assistantChart(chart)}</article>`).join("")}</section>` : ""}${chat.artifacts.length ? `<section class="card space"><div class="card-head"><h2>Reports</h2></div><div class="card-body data-reports">${[...chat.artifacts].reverse().map(item => `<div class="between"><span>${svg("file")} ${esc(item.title)}${item.row_count !== undefined ? ` · ${item.row_count} rows` : ""}</span><button class="btn secondary" data-action="assistant-export" data-artifact="${item.id}">${svg("download")}Save Excel</button></div>`).join("")}</div></section>` : ""}<section class="card data-composer"><form id="assistant-form" class="card-body"><label for="assistant-request">${active ? "Request in progress" : "Continue the conversation"}</label><textarea id="assistant-request" class="input command-input" required minlength="3" maxlength="3000" ${active || A.busy ? "disabled" : ""} placeholder="Now show only unpaid orders, sorted by amount.">${esc(A.draft)}</textarea><div class="data-send"><button class="btn primary" type="submit" ${active || A.busy ? "disabled" : ""}>Send ${svg("arrow")}</button></div>${A.error ? `<p class="error-text" role="alert">${esc(A.error)}</p>` : ""}</form></section>`;
}

function assistantReviewCard(turn, active) {
  const batch = turn.review_batch;
  if (!batch) return "";
  return `<section class="data-review-card"><div class="between"><h3>Reconciliation review</h3>${badge(batch.status)}</div><section class="stats space" aria-label="Reconciliation progress">${[[batch.input_rows, "Input rows"], [batch.matched_rows, "Completed"], [batch.unresolved_rows, "Needs attention"], [batch.archive_receipts, "Archive receipts"]].map(([value, label]) => `<div class="stat"><span>${label}</span><strong>${value}</strong></div>`).join("")}</section><div class="flex">${active || batch.busy ? "" : batch.review_tasks.map(task => `<a class="btn primary" href="#task/${task.job_id}/${batch.id}/review">Open review ${svg("arrow")}</a>`).join("")}<a class="btn secondary" href="#batch/${batch.id}">Open batch</a>${batch.report_available && !active ? `<button class="btn secondary" data-action="assistant-review-export" data-batch="${batch.id}">${svg("download")}Excel report</button>` : ""}</div></section>`;
}

function assistantTable(table) {
  return `<section class="card space"><div class="card-head between"><h2>Latest result</h2><span class="pill">${table.preview.length} of ${table.rows} rows · ${esc(table.frame_id)}</span></div><div class="table-wrap"><table><thead><tr>${table.columns.map(column => `<th>${esc(column)}</th>`).join("")}</tr></thead><tbody>${table.preview.map(row => `<tr>${row.map(value => `<td>${esc(value)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></section>`;
}

function assistantChart(chart) {
  const values = chart.values.map(Number), width = 720, height = 280;
  const palette = ["#526a80", "#8494a3", "#aaa09a", "#77788c", "#b5b1a4", "#627b94"];
  const n = value => new Intl.NumberFormat("en-US", {maximumFractionDigits: 3}).format(value);
  let shapes = "";
  if (chart.kind === "pie") {
    const total = values.reduce((sum, value) => sum + value, 0); let start = -Math.PI / 2;
    values.forEach((value, index) => {
      const end = start + value / total * Math.PI * 2, cx = 180, cy = 135, radius = 105;
      const x1 = cx + radius * Math.cos(start), y1 = cy + radius * Math.sin(start);
      const x2 = cx + radius * Math.cos(end), y2 = cy + radius * Math.sin(end);
      shapes += value === total ? `<circle cx="180" cy="135" r="105" fill="${palette[index % palette.length]}"/>` : `<path d="M ${cx} ${cy} L ${x1} ${y1} A ${radius} ${radius} 0 ${end - start > Math.PI ? 1 : 0} 1 ${x2} ${y2} Z" fill="${palette[index % palette.length]}"><title>${esc(chart.labels[index])}: ${esc(chart.values[index])}</title></path>`;
      if (index < 12) shapes += `<rect x="340" y="${18 + index * 20}" width="10" height="10" fill="${palette[index % palette.length]}"/><text x="360" y="${28 + index * 20}" font-size="12">${esc(String(chart.labels[index]).slice(0, 30))}: ${n(value)}</text>`;
      start = end;
    });
  } else {
    const min = Math.min(0, ...values), max = Math.max(0, ...values), range = max - min || 1;
    const y = value => 220 - (value - min) / range * 190;
    const step = 620 / Math.max(values.length, 1), x = index => 70 + step * (index + .5);
    [min, (min + max) / 2, max].forEach(value => { shapes += `<line x1="65" y1="${y(value)}" x2="700" y2="${y(value)}" stroke="#e5e4df"/><text x="58" y="${y(value) + 4}" text-anchor="end" font-size="11">${n(value)}</text>`; });
    if (chart.kind === "line") shapes += `<polyline points="${values.map((value, index) => `${x(index)},${y(value)}`).join(" ")}" fill="none" stroke="#526a80" stroke-width="2.5"/>`;
    values.forEach((value, index) => {
      const title = `<title>${esc(chart.labels[index])}: ${esc(chart.values[index])}</title>`;
      shapes += chart.kind === "bar" ? `<rect x="${x(index) - step * .3}" y="${Math.min(y(value), y(0))}" width="${Math.max(2, step * .6)}" height="${Math.max(1, Math.abs(y(value) - y(0)))}" rx="2" fill="#526a80">${title}</rect>` : `<circle cx="${x(index)}" cy="${y(value)}" r="3.5" fill="#526a80">${title}</circle>`;
      if (values.length <= 12 || index % Math.ceil(values.length / 12) === 0) shapes += `<text x="${x(index)}" y="244" text-anchor="middle" font-size="10">${esc(String(chart.labels[index]).slice(0, 12))}</text>`;
    });
  }
  return `<svg class="data-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(chart.title)}"><title>${esc(chart.title)}</title>${shapes}</svg>`;
}

async function refreshAssistant() {
  A.chats = (await api("/assistant/chats")).chats;
  A.chat = S.route === "assistant" && S.id ? await api("/assistant/chats/" + S.id) : null;
  if (A.chat) { A.folder = A.chat.folder; A.biFolder = A.chat.bi_folder || ""; }
}

async function assistantSubmit() {
  if (A.busy) return;
  A.busy = true; A.error = ""; render();
  try {
    const instruction = A.draft.trim();
    let chat = S.route === "assistant" ? A.chat : null;
    if (!chat) chat = await post("/assistant/chats", {folder: A.folder.trim(), bi_folder: A.biFolder.trim() || null});
    const response = await post(`/assistant/chats/${chat.id}/turns`, {instruction});
    A.draft = "";
    go("assistant/" + response.chat_id);
  } catch (error) { A.error = error.message; }
  finally { A.busy = false; render(); }
}

async function assistantAction(action, target) {
  if (action === "assistant-new") { A.chat = null; A.draft = ""; A.error = ""; go("assistant"); }
  else if (action === "assistant-pick" || action === "assistant-pick-bi") {
    target.disabled = true;
    try { const result = await post("/batches/pick-folder"); if (result.folder) { if (action === "assistant-pick-bi") A.biFolder = result.folder; else A.folder = result.folder; render(); } }
    finally { target.disabled = false; }
  } else if (action === "assistant-retry") {
    if (A.busy || A.chat?.active_turn) return;
    const turn = A.chat?.turns.find(item => item.id === Number(target.dataset.turn));
    if (!turn) return;
    A.busy = true; A.error = ""; render();
    try {
      await post(`/assistant/chats/${A.chat.id}/turns`, {instruction: turn.instruction, retry_turn_id: turn.id});
      A.chat = await api("/assistant/chats/" + A.chat.id);
    } catch (error) { A.error = error.message; }
    finally { A.busy = false; render(); }
  } else if (action === "assistant-cancel") {
    await post(`/assistant/turns/${target.dataset.turn}/cancel`); target.disabled = true;
  } else if (action === "assistant-review-export") {
    target.disabled = true;
    try {
      const result = await post(`/batches/${target.dataset.batch}/export`);
      if (result.download_url) { const link = document.createElement("a"); link.href = result.download_url; link.download = ""; document.body.append(link); link.click(); link.remove(); }
      else if (result.saved) toast("Excel report saved.");
    } finally { target.disabled = false; }
  } else if (action === "assistant-export") {
    target.disabled = true;
    try {
      const result = await post(`/assistant/artifacts/${target.dataset.artifact}/export`);
      if (result.download_url) { const link = document.createElement("a"); link.href = result.download_url; link.download = ""; document.body.append(link); link.click(); link.remove(); }
      else if (result.saved) toast("Excel report saved.");
    } finally { target.disabled = false; }
  }
}

document.addEventListener("input", event => {
  if (event.target.id === "assistant-request") A.draft = event.target.value;
  if (event.target.id === "assistant-folder") A.folder = event.target.value;
  if (event.target.id === "assistant-bi-folder") A.biFolder = event.target.value;
});
document.addEventListener("change", event => {
  if (event.target.id === "assistant-history" && event.target.value) { A.error = ""; A.draft = ""; go("assistant/" + event.target.value); }
});
setInterval(async () => {
  if (A.polling || S.route !== "assistant" || !S.session?.username || !A.chat?.active_turn) return;
  A.polling = true; const chatId = A.chat.id, token = S.token;
  try {
    const chat = await api("/assistant/chats/" + chatId);
    if (S.token === token && S.route === "assistant" && S.id === chatId) { A.chat = chat; render(); }
  } catch (error) { toast(error.message, true); }
  finally { A.polling = false; }
}, 1200);
