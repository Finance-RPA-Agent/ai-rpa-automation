"use strict";
const icons = {
  logo: "M6 20V4h15 M6 12h11",
  grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  list: "M8 6h13 M8 12h13 M8 18h13 M3 6h.01 M3 12h.01 M3 18h.01",
  plus: "M12 5v14 M5 12h14",
  file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M8 13h8 M8 17h5",
  check: "M5 12l4 4L19 6",
  arrow: "M4 12h16 M14 6l6 6-6 6",
  chevron: "M9 5l7 7-7 7",
  alert: "M12 3L2 21h20z M12 9v5 M12 18h.01",
  download: "M12 3v12 M7 10l5 5 5-5 M5 16v5h14v-5",
  upload: "M12 16V4 M7 9l5-5 5 5 M5 15v6h14v-6",
  search: "M21 21l-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
  database:
    "M20 6c0 2-16 2-16 0s16-2 16 0 M4 6v12c0 4 16 4 16 0V6 M4 12c0 3 16 3 16 0",
  settings: "M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6",
  logout: "M9 4H4v16h5 M10 12h12 M17 7l5 5-5 5",
  shield: "M12 3L4 6v6c0 5 8 9 8 9s8-4 8-9V6z M8 12l3 3 5-6",
  close: "M6 6l12 12 M6 18L18 6",
  play: "M7 4l14 8-14 8z",
  refresh: "M20 8a9 9 0 1 0 1 8 M20 3v6h-6",
  chart: "M4 20h17 M7 16v-5 M12 16V7 M17 16V3",
  info: "M12 11v6 M12 7h.01 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
};
const svg = (n) =>
  `<svg aria-hidden="true" viewBox="0 0 24 24"><path d="${icons[n] || icons.file}"/></svg>`;
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
// Format decimal text without converting financial values to binary floats.
const amount = (v) => {
  const value = String(v ?? "")
    .trim()
    .replaceAll(",", "");
  if (!/^[+-]?\d+(?:\.\d{1,2})?$/.test(value)) return esc(v || "—");
  const [whole, fraction = ""] = value.split(".");
  return esc(
    whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + "." + fraction.padEnd(2, "0"),
  );
};
const date = (v) =>
  v
    ? new Date(v).toLocaleString("en-GB", {
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : "—";
const statusNames = {
  pending: "Ready",
  running: "Running",
  waiting_confirmation: "Needs review",
  completed: "Completed",
  failed: "Stopped",
  cancelled: "Cancelled",
  generating: "Generating",
  ready: "Ready",
  scanned: "Scanned",
  scanning: "Scanning",
  needs_review: "Needs review",
};
const badge = (v, label) =>
  `<span class="badge ${v}">${esc(label || statusNames[v] || v)}</span>`;
const fieldNames = {
  supplier_id: "Supplier ID",
  supplier_name: "Supplier name",
  order_id: "Order ID",
  amount: "Amount",
  date: "Date",
  payment_status: "Payment status",
  record_status: "Record status",
};
const FIELDS = Object.keys(fieldNames);
const issueNames = {
  amount_mismatch: "Amount mismatch",
  payment_status_mismatch: "Payment status mismatch",
  record_status_mismatch: "Record status mismatch",
  missing_value: "Missing required value",
  missing_column: "Missing required column",
  invalid_amount: "Invalid amount",
  invalid_date: "Invalid date",
  duplicate_business_key: "Duplicate order key",
  record_not_found: "No matching BI record",
  ambiguous_reference: "Ambiguous BI reference",
  empty_dataset: "No order records",
};
const display = (v, field) =>
  v === null || v === undefined || v === ""
    ? "Not provided"
    : field === "amount"
      ? amount(v)
      : esc(v);
const S = {
  commands: [],
  commandDraft: "",
  commandFolder: "",
  commandBiFolder: "",
  commandPlan: null,
  commandBusy: false,
  commandError: "",
  batches: [],
  batch: null,
  batchTab: "exceptions",
  folderDraft: "",
  biFolderDraft: "",
  batchPolling: false,
  session: null,
  tasks: [],
  files: [],
  task: null,
  active: null,
  route: "dashboard",
  id: null,
  token: 0,
  selected: new Set(),
  tab: "records",
  search: "",
  filter: "all",
  draft: {
    title: "Supplier order reconciliation",
    instruction:
      "Reconcile the source orders with the imported BI reference. Pause for human review of differences before archiving clean results.",
    source_id: "",
    reference_id: "",
    ai: true,
  },
};
const app = document.getElementById("app");
let toastTimer;
function toast(message, error = false) {
  const element = document.getElementById("toast");
  element.textContent = message;
  element.className = "show" + (error ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (element.className = ""), 5000);
}
async function api(path, options = {}) {
  let response;
  try {
    response = await fetch("/api" + path, {
      ...options,
      headers: {
        "X-Requested-With": "FinanceFlow",
        ...(options.body instanceof FormData
          ? {}
          : { "Content-Type": "application/json" }),
        ...options.headers,
      },
    });
  } catch {
    throw new Error("The local service is unavailable. Restart Finance Flow.");
  }
  if (response.status === 401 && path !== "/login" && path !== "/setup") {
    S.session = { setup_required: false, username: null };
    render();
    throw new Error("Your session has expired. Please sign in again.");
  }
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("The service returned an unreadable response.");
  }
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(
      Array.isArray(detail)
        ? detail.map((d) => d.msg).join(" ")
        : detail || "The operation could not be completed.",
    );
  }
  return data;
}
const post = (path, body = {}) =>
  api(path, { method: "POST", body: JSON.stringify(body) });
const go = (route) => {
  if (location.hash === "#" + route) navigate();
  else location.hash = route;
};
const btn = (text, action, kind = "primary", extra = "") =>
  `<button class="btn ${kind}" data-action="${action}" ${extra}>${text}</button>`;
const brand = () =>
  `<div class="brand"><div class="brand-mark">${svg("logo")}</div><span>Finance Flow</span></div>`;
function heading(title, sub, actions = "") {
  return `<div class="heading between"><div><h1>${title}</h1></div><div class="flex">${actions}</div></div>`;
}
function auth() {
  const setup = S.session?.setup_required;
  return `<div class="auth"><header class="auth-header">${brand()}</header><main class="auth-main"><section class="auth-form" aria-labelledby="auth-title"><h1 id="auth-title">${setup ? "Create your workspace" : "Welcome back"}</h1><form id="auth-form"><div class="field"><label for="username">Username</label><input id="username" class="input" required minlength="2" maxlength="64" autocomplete="username" placeholder="e.g. Richard Xu"></div><div class="field"><label for="password">Password</label><input id="password" class="input" type="password" required minlength="${setup ? 6 : 1}" maxlength="256" autocomplete="${setup ? "new-password" : "current-password"}"></div><button class="btn primary" type="submit">${setup ? "Create workspace" : "Sign in"} ${svg("arrow")}</button><p class="error-text" id="auth-error" role="alert"></p></form></section></main></div>`;
}
function shell(body) {
  const active =
    S.route === "task" ? "tasks" : S.route === "batch" ? "batches" : S.route;
  const waiting = S.tasks.filter(
    (t) => t.status === "waiting_confirmation",
  ).length;
  const navigation = [
    ["dashboard", "grid", "Overview"],
    ["assistant", "list", "Data assistant"],
    ["batches", "database", "Folder batches"],
    ["tasks", "list", "Reconciliations"],
    ["new", "plus", "New reconciliation"],
    ["files", "file", "Files & references"],
    ["archive", "database", "Local archive"],
    ["settings", "settings", "Settings"],
  ];
  const pageTitle =
    {
      dashboard: "Overview",
      assistant: "Data assistant",
      batches: "Folder batches",
      batch: "Batch details",
      tasks: "Reconciliations",
      new: "New reconciliation",
      files: "Files & references",
      task: "Task details",
      archive: "Local archive",
      settings: "Settings",
    }[S.route] || "Overview";
  return `<aside class="sidebar">${brand()}<div class="nav-label">Workspace</div><nav class="nav" aria-label="Main navigation">${navigation.map(([key, ico, label]) => `<a href="#${key}" title="${label}" aria-label="${label}" class="${key === active ? "active" : ""}" ${key === active ? 'aria-current="page"' : ""}>${svg(ico)}<span class="text">${label}</span>${key === "tasks" && waiting ? `<span class="count">${waiting}</span>` : ""}</a>`).join("")}</nav><div class="sidebar-bottom"><div class="between"><span class="local-status">${svg("shield")}Local workspace</span><button class="icon-btn" data-action="logout" title="Sign out" aria-label="Sign out">${svg("logout")}</button></div></div></aside><div class="shell"><header class="topbar"><div class="breadcrumbs">Workspace ${svg("chevron")}<span>${pageTitle}</span></div><div class="top-right"><div class="top-user"><div class="avatar">${esc(S.session.username.slice(0, 2).toUpperCase())}</div><span>${esc(S.session.username)}</span></div></div></header><main class="main">${body}</main></div>`;
}
function taskTable(tasks) {
  return tasks.length
    ? `<div class="table-wrap"><table><thead><tr><th>Reconciliation</th><th>Status</th><th>Records</th><th>Updated</th><th></th></tr></thead><tbody>${tasks.map((t) => `<tr><td><a class="task-cell" href="#task/${t.id}"><span class="file-icon">${svg("file")}</span><div><strong>${esc(t.title)}</strong><small>${t.code} · ${esc(t.source_name)}</small></div></a></td><td>${badge(t.plan_status === "generating" ? "generating" : t.status)}</td><td>${t.row_count || "—"}</td><td class="tiny muted">${date(t.updated_at)}</td><td><a class="accent" href="#task/${t.id}">${t.status === "waiting_confirmation" ? "Review" : "Open"} ${svg("chevron")}</a></td></tr>`).join("")}</tbody></table></div>`
    : `<div class="empty">${svg("file")}<h3>No reconciliations yet</h3></div>`;
}
function commandCard() {
  const busy = S.commandBusy;
  const plan = S.commandPlan;
  return `<section class="card command-card" aria-label="Natural language task"><div class="card-head"><h2>What would you like to reconcile?</h2></div><form id="command-form" class="card-body"><label for="command-instruction">Your request</label><textarea id="command-instruction" class="input command-input" required minlength="3" maxlength="3000" ${busy ? "disabled" : ""} placeholder="Reconcile the orders in D:\\Finance\\Inbox against its reference files, keep exceptions for my review, and create an Excel report.">${esc(S.commandDraft)}</textarea><div class="input-folders">${folderInput("command-folder", "Input folder", S.commandFolder, "command-pick", true, busy)}${folderInput("command-bi-folder", "BI system folder", S.commandBiFolder, "command-pick-bi", true, busy)}</div><div class="data-send"><button class="btn primary" type="submit" ${busy ? "disabled" : ""}>${busy ? "Preparing…" : "Prepare task"}</button></div>${S.commandError ? `<p class="error-text" role="alert">${esc(S.commandError)}</p>` : ""}</form>${plan ? `<div class="command-plan"><h3>Execution plan</h3>${folderLocations(plan.folder, plan.bi_folder)}<ol>${plan.plan.steps.map(step => `<li>${esc(step)}</li>`).join("")}</ol><button class="btn primary" data-action="command-execute" ${busy ? "disabled" : ""}>${busy ? "Starting…" : "Run task"} ${svg("arrow")}</button></div>` : ""}</section>${S.commands.length ? `<section class="card space"><div class="card-head"><h2>Recent requests</h2></div><div class="command-history">${S.commands.slice(0, 5).map(command => `<div class="command-history-row"><div><strong>${esc(command.instruction)}</strong><div>${badge(command.status)}</div></div>${command.batch_id ? `<a class="btn secondary" href="#batch/${command.batch_id}">Open</a>` : `<button class="btn secondary" data-action="command-load" data-command="${command.id}">Open plan</button>`}</div>`).join("")}</div></section>` : ""}`;
}
async function commandAction(action, target) {
  if (action === "command-pick" || action === "command-pick-bi") {
    target.disabled = true;
    try {
      const chosen = await post("/batches/pick-folder");
      if (chosen.folder) {
        if (action === "command-pick-bi") S.commandBiFolder = chosen.folder;
        else S.commandFolder = chosen.folder;
        S.commandPlan = null;
        render();
      }
    } finally { target.disabled = false; }
  } else if (action === "command-load") {
    const plan = S.commands.find(command => command.id === target.dataset.command);
    if (!plan) return;
    S.commandPlan = plan;
    S.commandDraft = plan.instruction;
    S.commandFolder = plan.folder;
    S.commandBiFolder = plan.bi_folder || "";
    S.commandError = "";
    render();
  } else if (action === "command-execute") {
    if (!S.commandPlan || S.commandBusy) return;
    S.commandBusy = true;
    S.commandError = "";
    render();
    try {
      const batch = await post(`/commands/${S.commandPlan.id}/execute`);
      S.commandPlan = null;
      S.batchTab = "exceptions";
      go("batch/" + batch.id);
    } catch (error) {
      S.commandError = error.message;
    } finally {
      S.commandBusy = false;
      render();
    }
  }
}
async function prepareCommand() {
  if (S.commandBusy) return;
  S.commandBusy = true;
  S.commandPlan = null;
  S.commandError = "";
  render();
  try {
    const result = await post("/commands/prepare", {
      instruction: S.commandDraft.trim(), folder: S.commandFolder.trim() || null, bi_folder: S.commandBiFolder.trim() || null,
    });
    if (result.status === "needs_input") S.commandError = result.message;
    else {
      S.commandPlan = result;
      S.commandFolder = result.folder;
      S.commandBiFolder = result.bi_folder || "";
      S.commands = (await api("/commands")).commands;
    }
  } catch (error) { S.commandError = error.message; }
  finally { S.commandBusy = false; render(); }
}
function overview() {
  const complete = S.tasks.filter((t) => t.status === "completed");
  const waiting = S.tasks.filter((t) => t.status === "waiting_confirmation");
  const summary = [
    [S.tasks.length, "Total tasks", "All reconciliations"],
    [waiting.length, "Needs review", "Waiting for your decision"],
    [complete.length, "Completed", "Reconciled successfully"],
    [
      S.tasks.reduce((n, t) => n + t.archive_count, 0),
      "Archived records",
      "Saved locally",
    ],
  ];
  return `${heading("Overview", "Run folder batches automatically, or review individual reconciliations.", `<a href="#batches" class="btn ${waiting.length ? "secondary" : "primary"}">${svg("plus")}New folder batch</a>`)}${assistantEntry()}<section class="stats space" aria-label="Reconciliation summary">${summary.map(([n, label, description]) => `<div class="stat"><span>${label}</span><strong>${n}</strong></div>`).join("")}</section>${waiting.length ? `<section class="notice warn"><div><h3>${waiting.length} ${waiting.length === 1 ? "task needs" : "tasks need"} your review</h3></div><a class="btn primary" href="#task/${waiting[0].id}">Review findings ${svg("arrow")}</a></section>` : ""}<section class="card overview-section"><div class="card-head between"><h2>Recent reconciliations</h2><a href="#tasks" class="tiny accent">View all ${svg("arrow")}</a></div>${taskTable(S.tasks.slice(0, 5))}</section>`;
}
function tasksPage() {
  const tasks = filteredTasks();
  return `${heading("Reconciliations", "Follow every task from imported files to its final audit trail.", `<a href="#new" class="btn primary">${svg("plus")}New reconciliation</a>`)}<section class="card"><div class="toolbar"><label class="search">${svg("search")}<input id="task-search" aria-label="Search reconciliations" value="${esc(S.search)}" placeholder="Search title, file or task ID"></label><select id="task-filter" aria-label="Filter by status"><option value="all">All statuses</option>${Object.entries(
    statusNames,
  )
    .filter(
      ([key]) =>
        ![
          "ready",
          "generating",
          "scanned",
          "scanning",
          "needs_review",
        ].includes(key),
    )
    .map(
      ([key, label]) =>
        `<option value="${key}" ${S.filter === key ? "selected" : ""}>${label}</option>`,
    )
    .join(
      "",
    )}</select><span class="tiny muted" style="margin-left:auto">${tasks.length} tasks</span></div><div id="task-results">${taskTable(tasks)}</div></section>`;
}
function filteredTasks() {
  return S.tasks.filter(
    (t) =>
      (S.filter === "all" || t.status === S.filter) &&
      [t.title, t.source_name, t.code].some((v) =>
        v.toLowerCase().includes(S.search.toLowerCase()),
      ),
  );
}
function fileSelect(role) {
  const items = S.files.filter((f) => f.role === role);
  return `<select class="input" id="${role}-select" aria-label="${role === "source" ? "Source orders" : "BI reference export"}" required><option value="">Choose ${role === "source" ? "source orders" : "BI reference export"}</option>${items.map((f) => `<option value="${f.id}" ${S.draft[role + "_id"] === f.id ? "selected" : ""}>${esc(f.name)} · ${f.row_count} rows${f.ready ? "" : " · mapping needed"}</option>`).join("")}</select><div class="upload-zone" data-dropzone="${role}">${svg("upload")}<strong>Choose a file or drop it here</strong><input type="file" accept=".xlsx,.csv" data-upload="${role}" aria-label="Upload ${role === "source" ? "source file" : "BI reference export"}"></div>`;
}
function newPage() {
  return `${heading("New reconciliation", "Choose your files, then create a reconciliation task.")}<div class="stack"><section class="card"><div class="card-head"><h2>Task details</h2></div><form id="task-form" class="card-body"><div class="field"><label for="task-title">Task title</label><input id="task-title" class="input" required maxlength="120" value="${esc(S.draft.title)}"></div><div class="two-col"><div class="field"><label for="source-select">Source orders</label>${fileSelect("source")}</div><div class="field"><label for="reference-select">BI reference export</label>${fileSelect("reference")}</div></div><div class="field"><label for="task-instruction">Instructions</label><textarea id="task-instruction" class="input" required minlength="3" maxlength="3000">${esc(S.draft.instruction)}</textarea></div><label class="checkline"><input id="use-ai" type="checkbox" ${S.draft.ai ? "checked" : ""}><span>Use local AI to prepare the execution plan</span></label><div class="divider"></div><div class="between"><a class="tiny accent" href="/api/template">${svg("download")}Download field template</a><button type="submit" class="btn primary">Create task ${svg("arrow")}</button></div></form></section></div>`;
}
function filesPage() {
  return `${heading("Files & references", "Immutable local imports. Map your own column names to the required fields.", `<a href="/api/template" class="btn secondary">${svg("download")}Field template</a>`)}<div class="two-col"><section class="card"><div class="card-head"><h2>Import source orders</h2></div><div class="card-body">${fileSelect("source")}</div></section><section class="card"><div class="card-head"><h2>Import BI reference export</h2></div><div class="card-body">${fileSelect("reference")}</div></section></div><div class="notice space"><div><h3>Need a public example dataset?</h3></div><div class="flex"><a class="btn secondary" href="/api/examples/source">Source CSV</a><a class="btn secondary" href="/api/examples/reference">Reference CSV</a></div></div><div class="file-list space">${S.files.map((f) => `<article class="file-card"><div class="between"><h3>${svg("file")} ${esc(f.name)}</h3>${badge(f.ready ? "ready" : "pending", f.ready ? "Mapped" : "Mapping needed")}</div><p>${f.role === "reference" ? "BI reference" : "Source orders"} · ${f.row_count} rows · ${date(f.created_at)}</p><div class="between"><span class="tiny mono muted">${esc(f.sha256.slice(0, 12))}…</span>${btn("View mapping", "mapping", "ghost", `data-file-id="${f.id}"`)}</div></article>`).join("") || '<div class="empty"><h3>No records</h3></div>'}</div>`;
}
function logs(t) {
  return `<div class="card-body">${t.events.map((e) => `<div class="log"><time>${date(e.created_at)}</time><div><strong>${esc(e.action)}</strong><p>${esc(e.message.replaceAll("in the demo", "under the current reconciliation rules"))}</p></div></div>`).join("")}</div>`;
}
function records(t) {
  return `<div class="table-wrap"><table><thead><tr><th>Row</th><th>Supplier / Order</th><th>Amount</th><th>Payment</th><th>Finding</th></tr></thead><tbody>${t.records.map((r) => `<tr><td class="mono tiny">${r.original_row ?? r.row}</td><td>${esc(r.data.supplier_name || r.data.supplier_id || "Missing supplier")}<div class="tiny muted mono">${esc(r.data.order_id || "—")}</div></td><td class="mono">${display(r.data.amount, "amount")}</td><td>${esc(r.data.payment_status || "—")}</td><td>${t.issues.some((i) => i.row === r.row) ? badge("waiting_confirmation", "Needs review") : badge(t.status === "completed" ? "completed" : "pending", t.status === "completed" ? "Reconciled" : "Read")}</td></tr>`).join("")}</tbody></table>${!t.records.length ? '<div class="empty"><h3>No records</h3></div>' : ""}</div>${t.truncated_preview ? '<p class="detail-text card-body">Preview: first 100 rows</p>' : ""}`;
}
function finding(issue) {
  return `<article class="issue"><div class="top"><input type="checkbox" data-issue="${issue.id}" aria-label="Select ${esc(issueNames[issue.type] || issue.type)} on row ${issue.row || "header"}" ${S.selected.has(issue.id) ? "checked" : ""} ${issue.can_correct ? "" : "disabled"}><div><h3>${esc(issueNames[issue.type] || issue.type)}</h3><p class="meta">${issue.original_row ? "Source row " + issue.original_row : issue.row ? "Working row " + issue.row : "File-level finding"} · ${esc(issue.supplier_id || "—")} / ${esc(issue.order_id || "—")} · ${esc(fieldNames[issue.field] || "Record")}</p></div></div><div class="comparison"><div class="value"><span>Source</span><strong>${display(issue.original_value, issue.field)}</strong></div>${svg("arrow")}<div class="value reference"><span>BI reference</span><strong>${display(issue.reference_value, issue.field)}</strong></div></div><div class="issue-foot"><span>${issue.type === "amount_mismatch" ? "Difference " + amount(issue.difference) : issue.can_correct ? "Your decision is required" : "Correct the source file and create a new task"}</span>${issue.can_correct ? btn("Review correction", "correct", "ghost", `data-issue-id="${issue.id}"`) : ""}</div><p class="detail-text" style="margin:12px 0 0 24px">${esc(issue.message.replaceAll("in the demo", "under the current reconciliation rules"))}</p></article>`;
}
function reviewPanel(t) {
  return `<div class="between" style="margin-bottom:14px"><label class="checkline"><input id="select-findings" type="checkbox" ${t.issues.filter((i) => i.can_correct).length && t.issues.filter((i) => i.can_correct).every((i) => S.selected.has(i.id)) ? "checked" : ""}>Select correctable findings</label>${btn("Review selected corrections", "correct-selected", "primary", S.selected.size ? "" : "disabled")}</div>${t.issues.map(finding).join("")}${t.truncated_issues ? '<p class="detail-text">Preview: first 200 findings</p>' : ""}${!t.issues.length ? '<div class="info">' + svg("check") + "<div>No unresolved findings</div></div>" : ""}${t.decisions.length ? `<section class="card space"><div class="card-head"><h3>Human decision history</h3></div><div class="card-body">${t.decisions.map((d) => `<div class="log"><time>${date(d.created_at)}</time><div><strong>${esc(d.actor)} · Revision ${d.revision}</strong>${d.reason ? `<p>${esc(d.reason)}</p>` : ""}${d.changes.map((c) => `<p>Row ${c.original_row ?? c.source_row} · ${esc(fieldNames[c.field])}: ${display(c.before, c.field)} → ${display(c.after, c.field)}</p>`).join("")}</div></div>`).join("")}</div></section>` : ""}`;
}
function taskPage(t) {
  let banner = "";
  const planning = t.plan_status === "generating";
  if (planning || t.status === "running")
    banner = `<div class="notice"><div class="flex"><span class="busy accent"></span><div><h3>${planning ? "Generating a local execution plan" : esc(t.stage)}</h3></div></div>${btn("Request cancellation", "cancel", "secondary")}</div>`;
  else if (t.status === "completed")
    banner = `<div class="success-banner"><div class="success-icon">${svg("check")}</div><div><h2>Reconciliation complete</h2><p>${t.row_count} orders reconciled against your imported reference. ${t.archive_count} local archive receipts saved.</p></div></div>`;
  else if (t.status === "cancelled")
    banner = `<div class="notice"><div><h3>This task was cancelled.</h3></div><a href="#new" class="btn secondary">Create new task</a></div>`;
  else if (t.status === "waiting_confirmation")
    banner = `<div class="notice ${t.issue_count ? "warn" : ""}"><div><h3>${t.issue_count ? `${t.issue_count} ${t.issue_count === 1 ? "finding needs" : "findings need"} your review.` : "Corrections saved. Ready to revalidate."}</h3></div>${!t.issue_count ? btn("Resume & revalidate " + svg("arrow"), "run") : btn("Review findings " + svg("arrow"), "tab", "primary", 'data-tab="review"')}</div>`;
  else if (t.status === "failed")
    banner = `<div class="notice error"><div><h3>The operation stopped.</h3><p>${esc(t.error || "Execution was interrupted.")}</p></div>${btn(t.plan_status === "ready" ? "Retry execution" : "Retry plan", t.plan_status === "ready" ? "run" : "plan", "secondary")}</div>`;
  else
    banner = `<div class="notice"><div><h3>${t.plan_status === "ready" ? "Review the plan before starting." : "Generate a plan for this reconciliation."}</h3></div>${btn(t.plan_status === "ready" ? "Approve plan & run " + svg("play") : "Generate plan " + svg("arrow"), t.plan_status === "ready" ? "run" : "plan")}</div>`;
  return `${t.batch_id ? `<a class="batch-back" href="#batch/${t.batch_id}">← Back to folder batch</a>` : ""}${heading(esc(t.title), `${t.code} · Revision ${t.revision} · ${date(t.updated_at)}`, badge(planning ? "generating" : t.status))}${banner}<div class="stack"><div class="stack"><section class="card"><div class="card-head between"><h2>Reconciliation details</h2><span class="pill">Source currency retained</span></div><div class="task-summary">${[
    [t.row_count, "Records"],
    [t.issue_count, "Findings"],
    [t.archive_count, "Archived"],
    [t.decisions.length, "Decisions"],
  ]
    .map(([n, l]) => `<div><strong>${n}</strong><span>${l}</span></div>`)
    .join("")}</div><div class="tabs">${[
    ["records", "Records"],
    ["review", "Findings"],
    ["history", "Audit trail"],
  ]
    .map(
      ([key, l]) =>
        `<button data-action="tab" data-tab="${key}" class="${S.tab === key ? "active" : ""}">${l}</button>`,
    )
    .join(
      "",
    )}</div>${S.tab === "records" ? records(t) : S.tab === "history" ? logs(t) : `<div class="card-body">${reviewPanel(t)}</div>`}</section>${t.status === "completed" ? `<section class="card card-body"><h3>Download results</h3><div class="flex"><a href="/api/tasks/${t.id}/report" class="btn primary">${svg("download")}Full JSON report</a><a href="/api/tasks/${t.id}/export" class="btn secondary">${svg("download")}Reconciled CSV</a></div></section>` : ""}</div><div class="stack"><section class="card"><div class="card-head"><h3>Task evidence</h3></div><div class="card-body">${[
    ["Source", t.source_name],
    ["BI export", t.reference_name],
    ["Revision", t.revision],
    ["Amount total", amount(t.amount)],
    [
      "Plan mode",
      !t.plan
        ? "Not generated"
        : t.plan.mode === "local_ai"
          ? "Local AI"
          : "Standard checks",
    ],
    ["Model", t.plan?.model || "Not used"],
  ]
    .map(
      ([k, v]) =>
        `<div class="key-row"><span>${k}</span><strong>${esc(v)}</strong></div>`,
    )
    .join(
      "",
    )}<details class="evidence-details space"><summary>File fingerprints</summary><p class="detail-text space">Source SHA-256<br><span class="mono">${esc(t.source_sha256.slice(0, 20))}…</span></p><p class="detail-text space">BI reference SHA-256<br><span class="mono">${esc(t.reference_sha256.slice(0, 20))}…</span></p></details></div></section>${t.plan ? `<section class="card card-body"><details class="plan-details" ${t.status === "pending" && t.plan_status === "ready" ? "open" : ""}><summary>Execution plan</summary><div class="steps space">${t.plan.steps.map((s, i) => `<div class="step"><span class="step-number">${i + 1}</span><h3>${esc(s)}</h3></div>`).join("")}</div></details></section>` : ""}<a href="/api/tasks/${t.id}/report" class="btn secondary">${svg("download")}${t.status === "completed" ? "Download audit report" : "Download interim report"}</a>${!["completed", "cancelled", "running"].includes(t.status) && !planning ? btn("Cancel task", "cancel", "ghost") : ""}</div></div>`;
}
function archivePage() {
  const rows = S.archive || [];
  return `${heading("Local reconciliation archive", "Actual receipts produced by validated reconciliations. No enterprise OA connection is implied.")}<section class="card"><div class="card-head between"><h2>Archived records</h2><span class="pill">${rows.length} records</span></div><div class="table-wrap"><table><thead><tr><th>Archive receipt</th><th>Task</th><th>Supplier / Order</th><th>Amount</th><th>Recorded</th></tr></thead><tbody>${rows.map((r) => `<tr><td class="mono tiny">${esc(r.id)}</td><td><a href="#task/${r.job_id}" class="accent">FF-${String(r.job_id).padStart(5, "0")}</a></td><td>${esc(r.data.supplier_name || r.data.supplier_id)}<div class="tiny muted mono">${esc(r.data.order_id)}</div></td><td>${amount(r.data.amount)}</td><td class="tiny muted">${date(r.created_at)}</td></tr>`).join("")}</tbody></table>${rows.length ? "" : '<div class="empty">' + svg("database") + "<h3>No archived results yet.</h3></div>"}</div></section>`;
}
function settingsPage() {
  const model = S.model || {};
  return `${heading("Workspace settings", "Local model, data portability and account security.")}<div class="two-col"><div class="stack"><section class="card"><div class="card-head between"><h2>Local AI connection</h2>${badge(model.installed ? "ready" : "pending", model.installed ? "Ready" : "Setup required")}</div><div class="card-body">${[
    ["Provider", "Ollama · loopback only"],
    ["Model", model.model || "qwen3.5:4b"],
    ["Context window", "8,192 data / 4,096 reconciliation"],
    ["Concurrency", "One active task"],
    ["Cloud inference", "Disabled by application design"],
  ]
    .map(
      ([k, v]) =>
        `<div class="key-row"><span>${k}</span><strong>${v}</strong></div>`,
    )
    .join(
      "",
    )}<p class="detail-text space">${esc(model.message || "Checking local service…")}</p><div class="space">${btn(svg("refresh") + " Refresh connection", "refresh-model", "secondary")}</div></div></section><section class="card card-body"><h2>Data backup</h2><div class="space">${btn(svg("download") + " Download backup", "backup", "secondary")}</div></section></div><div class="stack"><section class="card"><div class="card-head"><h2>Change password</h2></div><form class="card-body" id="password-form"><div class="field"><label for="old-password">Current password</label><input id="old-password" class="input" type="password" required autocomplete="current-password"></div><div class="field"><label for="new-password">New password</label><input id="new-password" class="input" type="password" required minlength="6" maxlength="256" autocomplete="new-password"></div><button class="btn secondary" type="submit">Update password</button></form></section></div></div>`;
}
async function refresh() {
  const response = await api("/tasks");
  S.tasks = response.tasks;
  S.active = response.active_task;
  S.files = (await api("/files")).files;
  S.commands = (await api("/commands")).commands;
}
async function navigate() {
  const token = ++S.token;
  try {
    S.session = await api("/session");
    if (!S.session.username) {
      render();
      return;
    }
    const [route, id, context, requestedTab] = (location.hash.slice(1) || "dashboard").split(
      "/",
    );
    if (route === "task" && requestedTab === "review") S.tab = "review";
    S.contextBatch =
      route === "task" && /^\d+$/.test(context || "") ? Number(context) : null;
    S.route = [
      "dashboard",
      "assistant",
      "tasks",
      "batches",
      "batch",
      "new",
      "files",
      "task",
      "archive",
      "settings",
    ].includes(route)
      ? route
      : "dashboard";
    S.id = /^\d+$/.test(id || "") ? Number(id) : null;
    await refresh();
    if (token !== S.token) return;
    if (S.route === "task" && S.id) {
      S.task = await api(taskDetailPath(S.id));
      S.selected.clear();
    }
    if (S.route === "batches") {
      const folders = await api("/batches");
      S.batches = folders.batches;
      S.activeBatch = folders.active_batch;
      if (!S.folderDraft && S.batches.length && S.batches[0].bi_folder) {
        S.folderDraft = S.batches[0].folder;
        S.biFolderDraft = S.batches[0].bi_folder;
      }
      if (!S.commandFolder) S.commandFolder = S.folderDraft;
      if (!S.commandBiFolder) S.commandBiFolder = S.biFolderDraft;
    }
    if (S.route === "batch" && S.id) S.batch = await api("/batches/" + S.id);
    if (S.route === "assistant") await refreshAssistant();
    if (S.route === "archive") S.archive = (await api("/archive")).records;
    if (S.route === "settings") S.model = await api("/model");
    if (token !== S.token) return;
    render();
    window.scrollTo(0, 0);
  } catch (error) {
    toast(error.message, true);
    if (!S.session?.username) render();
    else
      app.innerHTML = shell(
        `<div class="empty">${svg("alert")}<h3>Unable to open this view.</h3><p>${esc(error.message)}</p><a href="#dashboard" class="btn secondary">Return to overview</a></div>`,
      );
  }
}
function render() {
  if (!S.session?.username) {
    app.innerHTML = auth();
    return;
  }
  const views = {
    dashboard: overview,
    assistant: assistantPage,
    batches: batchesPage,
    batch: () => (S.batch ? batchPage(S.batch) : batchesPage()),
    tasks: tasksPage,
    new: newPage,
    files: filesPage,
    task: () => (S.task ? taskPage(S.task) : tasksPage()),
    archive: archivePage,
    settings: settingsPage,
  };
  app.innerHTML = shell((views[S.route] || overview)());
}
function modal(title, body, footer) {
  document.getElementById("modal").innerHTML =
    `<div class="modal-bg"><section class="modal-box" role="dialog" aria-modal="true" aria-labelledby="modal-title" tabindex="-1"><div class="modal-head between"><h2 id="modal-title">${title}</h2><button class="icon-btn" data-action="close-modal" aria-label="Close">${svg("close")}</button></div><div class="modal-body">${body}</div><div class="modal-footer">${footer}</div></section></div>`;
  document.querySelector(".modal-box").focus();
}
function closeModal() {
  document.getElementById("modal").innerHTML = "";
}
function mappingModal(file) {
  S.mappingFile = file;
  modal(
    "Confirm column mapping",
    `<form id="mapping-form">${FIELDS.map((field) => `<div class="map-row"><label for="map-${field}">${fieldNames[field]}</label><select id="map-${field}" required><option value="">Choose a source column</option>${file.columns.map((column) => `<option value="${esc(column)}" ${file.mapping[field] === column ? "selected" : ""}>${esc(column)}</option>`).join("")}</select></div>`).join("")}</form>`,
    `${btn("Close", "close-modal", "secondary")}<button form="mapping-form" type="submit" class="btn primary">Save mapping</button>`,
  );
}
async function importFile(file, role) {
  if (!file || !/\.(xlsx|csv)$/i.test(file.name))
    throw new Error("Choose an Excel .xlsx or UTF-8 .csv file.");
  if (!file.size || file.size > 10 * 1024 * 1024)
    throw new Error("Choose a nonempty file of at most 10 MB.");
  toast("Importing file…");
  const body = new FormData();
  body.append("file", file);
  body.append("role", role);
  const uploaded = await api("/files", { method: "POST", body });
  S.draft[role + "_id"] = uploaded.id;
  await refresh();
  render();
  mappingModal(uploaded);
}
function correctionModal(ids) {
  const chosen = S.task.issues.filter(
    (issue) => ids.includes(issue.id) && issue.can_correct,
  );
  if (!chosen.length) {
    toast("Choose a correctable finding first.", true);
    return;
  }
  S.reviewIssues = chosen;
  const single = chosen.length === 1;
  modal(
    "Confirm specific corrections",
    `<div class="correction-preview">${chosen.map((i) => `<div>Row ${i.original_row ?? i.row} · ${esc(fieldNames[i.field])}<br><strong>${display(i.original_value, i.field)} → ${display(i.reference_value, i.field)}</strong></div>`).join("")}</div><form id="review-form">${single ? `<div class="field"><label for="correction-mode">Replacement source</label><select id="correction-mode" class="input"><option value="reference">Use the shown BI reference value</option><option value="manual">Enter a specific replacement</option></select></div><div class="field" id="manual-field" hidden><label for="manual-value">Replacement value</label><input class="input" id="manual-value" maxlength="500"></div>` : ""}</form>`,
    `${btn("Back", "close-modal", "secondary")}<button form="review-form" type="submit" class="btn primary">Save corrections & revalidate</button>`,
  );
  document.getElementById("correction-mode")?.focus();
}
document.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-action]");
  if (!target || target.disabled) return;
  const action = target.dataset.action;
  try {
    if (action.startsWith("assistant-")) {
      await assistantAction(action, target);
    } else if (action.startsWith("command-")) {
      await commandAction(action, target);
    } else if (action.startsWith("batch-") || (action === "pick-folder" || action === "pick-bi-folder")) {
      await batchAction(action, target);
    } else if (action === "close-modal") closeModal();
    else if (action === "logout") {
      await post("/logout");
      S.session = { setup_required: false, username: null };
      render();
    } else if (action === "plan" || action === "run") {
      target.disabled = true;
      await post(`/tasks/${S.id}/${action}`);
      S.task = await api(taskDetailPath(S.id));
      render();
    } else if (action === "tab") {
      S.tab = target.dataset.tab;
      render();
    } else if (action === "mapping") {
      mappingModal(await api("/files/" + target.dataset.fileId));
    } else if (action === "correct") {
      correctionModal([target.dataset.issueId]);
    } else if (action === "correct-selected") {
      correctionModal([...S.selected]);
    } else if (action === "cancel") {
      modal(
        "Cancel this task?",
        ``,
        `${btn("Keep task", "close-modal", "secondary")}${btn("Confirm cancellation", "confirm-cancel", "danger")}`,
      );
    } else if (action === "confirm-cancel") {
      target.disabled = true;
      await post(`/tasks/${S.id}/cancel`);
      closeModal();
      S.task = await api(taskDetailPath(S.id));
      render();
      toast("Cancellation recorded.");
    } else if (action === "refresh-model") {
      target.disabled = true;
      S.model = await api("/model");
      render();
    } else if (action === "backup") {
      target.disabled = true;
      const response = await fetch("/api/backup", {
        method: "POST",
        headers: { "X-Requested-With": "FinanceFlow" },
      });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || "Backup failed.");
      }
      const blob = await response.blob();
      const href = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = href;
      link.download =
        /filename="([^"]+)"/.exec(
          response.headers.get("content-disposition") || "",
        )?.[1] || "finance-flow-backup.zip";
      link.click();
      setTimeout(() => URL.revokeObjectURL(href), 10000);
      toast("Backup downloaded.");
    }
  } catch (error) {
    toast(error.message, true);
  } finally {
    target.disabled = false;
  }
});
document.addEventListener("input", (event) => {
  const id = event.target.id;
  if (id === "command-instruction" || id === "command-folder" || id === "command-bi-folder") {
    if (id === "command-instruction") S.commandDraft = event.target.value;
    else if (id === "command-bi-folder") S.commandBiFolder = event.target.value;
    else S.commandFolder = event.target.value;
    S.commandPlan = null;
    document.querySelector(".command-plan")?.remove();
  }
  if (id === "folder-path") S.folderDraft = event.target.value;
  if (id === "bi-folder-path") S.biFolderDraft = event.target.value;
  if (id === "task-title") S.draft.title = event.target.value;
  if (id === "task-instruction") S.draft.instruction = event.target.value;
  if (id === "task-search") {
    S.search = event.target.value;
    document.getElementById("task-results").innerHTML =
      taskTable(filteredTasks());
  }
});
document.addEventListener("change", async (event) => {
  try {
    const target = event.target;
    if (target.id === "use-ai") S.draft.ai = target.checked;
    if (target.id === "source-select") S.draft.source_id = target.value;
    if (target.id === "reference-select") S.draft.reference_id = target.value;
    if (target.dataset.upload && target.files[0])
      await importFile(target.files[0], target.dataset.upload);
    if (target.id === "task-filter") {
      S.filter = target.value;
      render();
    }
    if (target.dataset.issue) {
      target.checked
        ? S.selected.add(target.dataset.issue)
        : S.selected.delete(target.dataset.issue);
      render();
    }
    if (target.id === "select-findings") {
      S.selected = target.checked
        ? new Set(S.task.issues.filter((i) => i.can_correct).map((i) => i.id))
        : new Set();
      render();
    }
    if (target.id === "correction-mode")
      document.getElementById("manual-field").hidden =
        target.value !== "manual";
  } catch (error) {
    toast(error.message, true);
  }
});
document.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const submit =
    document.querySelector(`[form="${form.id}"]`) ||
    form.querySelector("[type=submit]");
  if (submit) submit.disabled = true;
  try {
    if (form.id === "assistant-form") {
      await assistantSubmit();
    } else if (form.id === "command-form") {
      await prepareCommand();
    } else if (form.id === "folder-scan-form" || form.id === "batch-table-form") {
      await batchSubmit(form);
    } else if (form.id === "auth-form") {
      S.session = await post(S.session.setup_required ? "/setup" : "/login", {
        username: document.getElementById("username").value.trim(),
        password: document.getElementById("password").value,
      });
      await navigate();
    } else if (form.id === "task-form") {
      const task = await post("/tasks", S.draft);
      S.tab = "records";
      go("task/" + task.id);
    } else if (form.id === "mapping-form") {
      const mapping = Object.fromEntries(
        FIELDS.map((field) => [
          field,
          document.getElementById("map-" + field).value,
        ]),
      );
      await post("/files/" + S.mappingFile.id + "/mapping", { mapping });
      closeModal();
      await refresh();
      render();
      toast("Column mapping saved.");
    } else if (form.id === "review-form") {
      const mode =
        document.getElementById("correction-mode")?.value || "reference";
      const value = document.getElementById("manual-value")?.value || null;
      S.task = await post(`/tasks/${S.id}/review`, {
        revision: S.task.revision,
        evidence_digest: S.task.evidence_digest,
        changes: S.reviewIssues.map((i) => ({ issue_id: i.id, mode, value })),
      });
      if (S.contextBatch) S.task = await api(taskDetailPath(S.id));
      closeModal();
      S.selected.clear();
      render();
      toast("Corrections recorded and revalidated.");
    } else if (form.id === "password-form") {
      await post("/password", {
        current_password: document.getElementById("old-password").value,
        new_password: document.getElementById("new-password").value,
      });
      form.reset();
      toast("Password updated. Other sessions were signed out.");
    }
  } catch (error) {
    if (form.id === "auth-form")
      document.getElementById("auth-error").textContent = error.message;
    else toast(error.message, true);
  } finally {
    if (submit) submit.disabled = false;
  }
});
document.addEventListener("dragover", (event) => {
  const zone = event.target.closest("[data-dropzone]");
  if (zone) {
    event.preventDefault();
    zone.classList.add("dragging");
  }
});
document.addEventListener("dragleave", (event) =>
  event.target.closest("[data-dropzone]")?.classList.remove("dragging"),
);
document.addEventListener("drop", async (event) => {
  const zone = event.target.closest("[data-dropzone]");
  if (zone) {
    event.preventDefault();
    zone.classList.remove("dragging");
    try {
      await importFile(event.dataTransfer.files[0], zone.dataset.dropzone);
    } catch (error) {
      toast(error.message, true);
    }
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeModal();
  if (event.key === "Tab" && document.querySelector(".modal-box")) {
    const elements = [
      ...document
        .querySelector(".modal-box")
        .querySelectorAll("button,input,select,textarea"),
    ].filter((e) => !e.disabled && !e.closest("[hidden]"));
    if (event.shiftKey && document.activeElement === elements[0]) {
      event.preventDefault();
      elements.at(-1).focus();
    } else if (!event.shiftKey && document.activeElement === elements.at(-1)) {
      event.preventDefault();
      elements[0].focus();
    }
  }
});

// Folder batches use the same account, local worker and revision-bound review flow.
function taskDetailPath(id) {
  return "/tasks/" + id + (S.contextBatch ? "?batch_id=" + S.contextBatch : "");
}
function batchesPage() {
  const busy =
    S.activeBatch ||
    S.active ||
    S.batches.some((b) => ["running", "scanning"].includes(b.status));
  return `${heading("Folder batches", "Read a folder, reconcile clean rows automatically, and review only exceptions.")}${commandCard()}<section class="card space"><div class="card-head"><h2>Choose folders</h2></div><form id="folder-scan-form" class="card-body"><div class="input-folders">${folderInput("folder-path", "Input folder", S.folderDraft, "pick-folder", true, busy)}${folderInput("bi-folder-path", "BI system folder", S.biFolderDraft, "pick-bi-folder", true, busy)}</div><div class="data-send"><button class="btn primary" type="submit" ${busy ? "disabled" : ""}>${svg("search")}Scan folders</button></div></form></section><section class="card space"><div class="card-head"><h2>Recent folder batches</h2></div>${S.batches.length ? `<div class="table-wrap"><table><thead><tr><th>Batch</th><th>Input folder</th><th>BI system folder</th><th>Status</th><th>Created</th><th></th></tr></thead><tbody>${S.batches.map((b) => `<tr><td class="mono">BATCH-${String(b.id).padStart(5, "0")}</td><td class="batch-folder-cell" title="${esc(b.folder)}">${esc(b.folder)}</td><td class="batch-folder-cell" title="${esc(b.bi_folder || "")}">${esc(b.bi_folder || "—")}</td><td>${badge(b.status)}</td><td>${date(b.created_at)}</td><td><a class="accent" href="#batch/${b.id}">Open ${svg("chevron")}</a></td></tr>`).join("")}</tbody></table></div>` : `<div class="empty">${svg("file")}<h3>No folder batches yet</h3></div>`}</section>`;
}
function batchPage(b) {
  const busy = b.busy || ["scanning", "running"].includes(b.status);
  let message = "";
  if (busy)
    message = `<div class="notice"><div class="flex"><span class="busy accent"></span><div><h3>${b.status === "scanning" ? "Scanning folder" : b.status === "running" ? "Reconciling tables" : "Preparing Excel report"}</h3></div></div>${["scanning", "running"].includes(b.status) ? btn("Cancel batch", "batch-cancel", "secondary") : ""}</div>`;
  else if (b.status === "cancelled")
    message = `<div class="notice"><div><h3>This batch was cancelled</h3></div></div>`;
  else if (b.runnable_tables)
    message = `<div class="notice"><div><h3>${b.runnable_tables} ${b.runnable_tables === 1 ? "table is" : "tables are"} ready to run</h3></div>${btn("Run ready tables " + svg("play"), "batch-run")}</div>`;
  else if (b.status === "completed")
    message = `<div class="success-banner"><div class="success-icon">${svg("check")}</div><div><h2>Batch reconciliation complete</h2></div></div>`;
  else
    message = `<div class="notice warn"><div><h3>Only exceptions need your attention</h3></div></div>`;
  const stats = [
    [b.input_rows, "Input rows"],
    [b.matched_rows, "Completed rows"],
    [b.unresolved_rows, "Not completed"],
    [b.archive_receipts, "Archive receipts"],
  ];
  return `<a class="batch-back" href="#batches">← Folder batches</a>${heading(b.code, esc(b.folder), b.report_available ? btn(svg("download") + "Excel report", "batch-report", b.runnable_tables ? "secondary" : "primary") : badge(b.status))}${folderLocations(b.folder, b.bi_folder)}${b.command ? `<section class="card card-body command-origin"><h3>Your request</h3><p>${esc(b.command.instruction)}</p></section>` : ""}${message}${b.error ? `<div class="notice error"><div><h3>Operation details</h3><p>${esc(b.error)}</p></div></div>` : ""}<section class="stats" aria-label="Batch progress">${stats.map(([n, label]) => `<div class="stat"><span>${label}</span><strong>${n}</strong></div>`).join("")}</section><section class="card"><div class="tabs"><button data-action="batch-tab" data-tab="exceptions" class="${S.batchTab === "exceptions" ? "active" : ""}">Exceptions (${b.review_tasks.length + b.attention.length})</button><button data-action="batch-tab" data-tab="tables" class="${S.batchTab === "tables" ? "active" : ""}">All tables (${b.table_count})</button></div><div class="card-body">${S.batchTab === "tables" ? batchTables(b, busy) : batchExceptions(b, busy)}</div></section>`;
}
function batchExceptions(b, busy) {
  const reviews = b.review_tasks
    .map(
      (t) =>
        `<article class="batch-exception"><div class="between"><div><h3>${esc(t.title)}</h3><p class="detail-text">${t.row_count} rows held · ${t.issue_count} current ${t.issue_count === 1 ? "finding" : "findings"} · ${esc(t.code)}</p></div>${badge(t.status)}</div>${t.error ? `<p class="error-text">${esc(t.error)}</p>` : ""}<div class="between space">${busy ? '<span class="hint">Batch is active</span>' : `<a class="btn primary" href="#task/${t.job_id}/${b.id}">${t.status === "waiting_confirmation" ? "Open review" : "Open task"} ${svg("arrow")}</a>`}</div></article>`,
    )
    .join("");
  const setup = b.attention
    .map((item) => {
      const table = b.tables.find((t) => t.id === item.entry_id);
      return `<article class="batch-exception"><div class="between"><div><h3>${esc(item.file)} · ${esc(item.sheet || "File")}</h3></div>${!table.has_jobs ? btn("Resolve table", "batch-table", "secondary", `data-entry="${item.entry_id}" ${busy ? "disabled" : ""}`) : ""}</div><ul class="batch-problems">${item.messages.map((message) => `<li>${esc(message)}</li>`).join("")}</ul>${table.has_jobs ? '' : ""}</article>`;
    })
    .join("");
  return (
    reviews + setup ||
    `<div class="empty">${svg("check")}<h3>${busy ? "Checking the captured tables" : b.status === "completed" ? "No outstanding exceptions" : "No review tasks yet"}</h3></div>`
  );
}
function batchTables(b, busy) {
  return `<div class="table-wrap"><table><thead><tr><th>File / worksheet</th><th>Role</th><th>Rows</th><th>Reference</th><th>Status</th><th></th></tr></thead><tbody>${b.tables
    .map((t) => {
      const ref = b.tables.find((r) => r.id === t.reference_id);
      return `<tr><td><strong>${esc(t.file)}</strong><div class="tiny muted">${esc(t.sheet || "Unreadable file")}</div></td><td>${esc({ source: "Source", reference: "Reference", unknown: "Unclassified", skip: "Ignored" }[t.role])}</td><td>${t.row_count}</td><td>${ref ? esc(ref.file + " / " + ref.sheet) : "—"}</td><td>${badge(t.role === "skip" ? "cancelled" : t.problems.length ? "waiting_confirmation" : t.processed ? "completed" : "ready", t.role === "skip" ? "Ignored" : t.problems.length ? "Needs attention" : t.processed ? "Processed" : "Ready")}</td><td>${!t.has_jobs ? btn("Configure", "batch-table", "ghost", `data-entry="${t.id}" ${busy ? "disabled" : ""}`) : ""}</td></tr>`;
    })
    .join("")}</tbody></table></div>`;
}
function batchTableModal(entryId) {
  const table = S.batch.tables.find((t) => t.id === entryId);
  S.batchEntry = table;
  const refs = S.batch.tables.filter(
    (t) => t.role === "reference" && t.id !== table.id,
  );
  modal(
    "Configure table",
    `<p class="detail-text">${esc(table.file)} · ${esc(table.sheet || "File")}</p><form id="batch-table-form"><div class="two-col space"><div class="field"><label for="batch-role">Table role</label><select id="batch-role" class="input">${[
      ["source", "Source orders"],
      ["reference", "BI reference"],
      ["unknown", "Unclassified"],
      ["skip", "Ignore this table"],
    ]
      .filter(([role]) => !table.input_group || role === "skip" || role === (table.input_group === "bi" ? "reference" : "source"))
      .map(
        ([v, label]) =>
          `<option value="${v}" ${table.role === v ? "selected" : ""}>${label}</option>`,
      )
      .join(
        "",
      )}</select></div><div class="field"><label for="batch-reference">Reference table</label><select id="batch-reference" class="input"><option value="">Automatic matching</option>${refs.map((ref) => `<option value="${ref.id}" ${table.reference_id === ref.id ? "selected" : ""}>${esc(ref.file + " / " + ref.sheet)}</option>`).join("")}</select></div></div>${table.columns.length ? `<h3>Required field mapping</h3>${FIELDS.map((field) => `<div class="map-row"><label for="batch-map-${field}">${esc(fieldNames[field])}</label><select id="batch-map-${field}" class="input"><option value="">Choose a column</option>${table.columns.map((column) => `<option value="${esc(column)}" ${table.mapping[field] === column ? "selected" : ""}>${esc(column)}</option>`).join("")}</select></div>`).join("")}` : ''}</form>`,
    `${btn("Back", "close-modal", "secondary")}<button class="btn primary" form="batch-table-form" type="submit">Save table setup</button>`,
  );
}
async function batchAction(action, target) {
  if ((action === "pick-folder" || action === "pick-bi-folder")) {
    target.disabled = true;
    const chosen = await post("/batches/pick-folder");
    if (chosen.folder) {
      if (action === "pick-bi-folder") {
        S.biFolderDraft = chosen.folder;
        document.getElementById("bi-folder-path").value = chosen.folder;
      } else {
        S.folderDraft = chosen.folder;
        document.getElementById("folder-path").value = chosen.folder;
      }
    }
  } else if (action === "batch-run" || action === "batch-cancel") {
    target.disabled = true;
    S.batch = await post(
      `/batches/${S.id}/${action === "batch-run" ? "run" : "cancel"}`,
    );
    render();
  } else if (action === "batch-tab") {
    S.batchTab = target.dataset.tab;
    render();
  } else if (action === "batch-table")
    batchTableModal(Number(target.dataset.entry));
  else if (action === "batch-report") {
    target.disabled = true;
    const exported = await post(`/batches/${S.id}/export`);
    if (exported.handled) {
      toast(exported.saved ? "Excel report saved." : "Save cancelled.");
      return;
    }
    const response = await fetch(exported.download_url, {
      headers: { "X-Requested-With": "FinanceFlow" },
    });
    if (!response.ok) {
      const body = await response.json();
      throw new Error(
        body.detail || "The Excel report could not be generated.",
      );
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `FinanceFlow-${S.batch.code}.xlsx`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    toast("Excel report downloaded.");
  }
}
async function batchSubmit(form) {
  if (form.id === "folder-scan-form") {
    S.folderDraft = document.getElementById("folder-path").value.trim();
    S.biFolderDraft = document.getElementById("bi-folder-path").value.trim();
    const batch = await post("/batches/scan", { folder: S.folderDraft, bi_folder: S.biFolderDraft });
    S.batchTab = "exceptions";
    go("batch/" + batch.id);
  } else {
    const role = document.getElementById("batch-role").value;
    const rawReference = document.getElementById("batch-reference").value;
    const request = {
      role,
      reference_id:
        role === "source" && rawReference ? Number(rawReference) : null,
    };
    if (role !== "skip" && S.batchEntry.columns.length) {
      const mapping = Object.fromEntries(
        FIELDS.map((field) => [
          field,
          document.getElementById("batch-map-" + field).value,
        ]),
      );
      if (Object.values(mapping).some((v) => !v))
        throw new Error("Map all seven required fields, or choose Ignore.");
      request.mapping = mapping;
    }
    S.batch = await post(`/batches/${S.id}/tables/${S.batchEntry.id}`, request);
    closeModal();
    render();
    toast("Table setup saved.");
  }
}
setInterval(async () => {
  if (
    S.batchPolling ||
    !S.session?.username ||
    S.route !== "batch" ||
    !S.batch ||
    !(S.batch.busy || ["scanning", "running"].includes(S.batch.status))
  )
    return;
  S.batchPolling = true;
  const id = S.id,
    token = S.token;
  try {
    const batch = await api("/batches/" + id);
    if (token !== S.token || id !== S.id) return;
    S.batch = batch;
    if (!batch.busy) await refresh();
    render();
  } catch (error) {
    toast(error.message, true);
  } finally {
    S.batchPolling = false;
  }
}, 1200);

window.addEventListener("hashchange", navigate);
let polling = false;
setInterval(async () => {
  if (
    polling ||
    !S.session?.username ||
    S.route !== "task" ||
    !S.task ||
    (S.task.status !== "running" && S.task.plan_status !== "generating")
  )
    return;
  polling = true;
  const id = S.id,
    token = S.token;
  try {
    const task = await api(taskDetailPath(id));
    if (token !== S.token || S.id !== id) return;
    S.task = task;
    if (task.status !== "running" && task.plan_status !== "generating")
      await refresh();
    render();
  } catch (error) {
    toast(error.message, true);
  } finally {
    polling = false;
  }
}, 900);
navigate();
