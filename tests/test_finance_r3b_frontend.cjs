"use strict";
// Synthetic controller/API tests using Node builtins. No server/model/network is contacted.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const Advice = require("../product/static/issue-advice.js");
const digest = "a".repeat(64);
function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; }
function response(id = "issue-a", task = 1) {
  return { task_id: task, issue_id: id, revision: 2, evidence_digest: digest,
    mode: "local_model", status: "advice_ready", status_message: "Validated local evidence selection.", model: "qwen3.5:4b", advisory_only: true,
    facts: [{ id: "F_FINDING", source: "rule", label: "Finding", value: "amount_mismatch" },
      { id: "F_AMOUNT_SOURCE", source: "input", label: "Source amount", value: "9007199254740993.01" },
      { id: "F_AMOUNT_BI", source: "reference", label: "Imported BI amount", value: "9007199254740993.02" },
      { id: "F_AMOUNT_DIFF", source: "rule", label: "Source minus reference", value: "-0.01" }],
    explanation: "Neither source is assumed correct. The cause is unknown.",
    selected_fact_ids: ["F_FINDING", "F_AMOUNT_SOURCE", "F_AMOUNT_BI", "F_AMOUNT_DIFF"], uncertainty: "ROOT_CAUSE_UNKNOWN",
    suggestions: [{ id: "REVIEW_BOTH_SOURCES", text: "Verify both sources independently.", requires_human_decision: true }] };
}
function harness() {
  const state = { session: { username: "synthetic" }, token: 1, hash: "#task/1", route: "task", view: "review", taskId: 1,
    task: { id: 1, revision: 2, evidence_digest: digest, status: "waiting_confirmation", issues: [{ id: "issue-a", can_correct: true }, { id: "issue-b", can_correct: false }] } };
  const calls = [], timers = new Map(); let sequence = 0;
  const controller = Advice.create({ getContext: () => state,
    request: (url, body, guard) => { const wait = deferred(); calls.push({ url, body, guard, ...wait }); return wait.promise; },
    schedule: (fn, ms) => { const id = ++sequence; timers.set(id, { fn, ms }); return id; }, unschedule: id => timers.delete(id) });
  return { state, calls, timers, controller };
}
async function success(h, id = "issue-a", data = response(id)) { const pending = h.controller.explain(id); h.calls.at(-1).resolve(data); await pending; return h.controller.render(id); }

test("opening, rendering and refreshing creates no advice/model requests", () => {
  const h = harness(); for (let i = 0; i < 3; i++) { h.controller.sync(); h.controller.render("issue-a"); }
  h.controller.invalidate(); h.controller.render("issue-a"); assert.equal(h.calls.length, 0);
});
test("explicit click sends exact binding once and shows pending without AI success", async () => {
  const h = harness(), pending = h.controller.explain("issue-a");
  assert.equal(h.calls.length, 1); assert.equal(h.calls[0].url, "/tasks/1/issues/issue-a/explanation");
  assert.deepEqual(h.calls[0].body, { revision: 2, evidence_digest: digest });
  assert.match(h.controller.render("issue-a"), /disabled/); assert.match(h.controller.render("issue-a"), /First use can take longer/);
  assert.doesNotMatch(h.controller.render("issue-a"), /Local AI ·/);
  h.calls[0].resolve(response()); await pending;
});
test("local advice preserves exact Decimal text, sources, human gate and evidence", async () => {
  const h = harness(), html = await success(h);
  for (const s of ["9007199254740993.01", "9007199254740993.02", "-0.01", "Source input", "Imported BI reference", "Deterministic rule", "Local AI", "Human decision required", digest, "separate Review correction"]) assert.ok(html.includes(s), s);
  assert.equal(h.calls.length, 1); assert.deepEqual(h.state.task.issues.map(i => i.id), ["issue-a", "issue-b"]);
  assert.ok(h.calls.every(c => c.url.endsWith("/explanation")));
});
for (const status of ["model_timeout", "model_unavailable", "model_busy", "model_rejected", "model_error", "unsupported", "insufficient_evidence"]) {
  test("honest deterministic fallback: " + status, async () => {
    const h = harness(), data = response(); Object.assign(data, { mode: "rules_only", status, model: null });
    const html = await success(h, "issue-a", data);
    assert.match(html, /Rule-based only · deterministic fallback/); assert.ok(html.includes(status)); assert.doesNotMatch(html, /Local AI ·/);
  });
}
test("no-match/unsupported has no fabricated reference or zero amount", async () => {
  const h = harness(), data = response(); Object.assign(data, { mode: "rules_only", status: "unsupported", model: null,
    facts: [data.facts[0]], selected_fact_ids: ["F_FINDING"], explanation: "No matching record. No reference value is established." });
  const html = await success(h, "issue-a", data); assert.doesNotMatch(html, /900719925|0\.00|Imported BI amount/);
});
const invalid = {
  "unknown top-level executable field": d => { d.approve = true; },
  "advisory_only false": d => { d.advisory_only = false; },
  "human decision false": d => { d.suggestions[0].requires_human_decision = false; },
  "unknown action": d => { d.suggestions[0].id = "PAY_NOW"; },
  "unknown fact": d => { d.facts[0].id = "UNVERIFIED"; },
  "wrong fact source": d => { d.facts[0].source = "reference"; },
  "non-text financial value": d => { d.facts[1].value = 9007199254740993; },
  "unknown selected fact": d => { d.selected_fact_ids.push("UNKNOWN"); },
  "duplicate suggestion": d => { d.suggestions.push(d.suggestions[0]); },
  "wrong model": d => { d.model = "remote-model"; },
  "AI label with fallback status": d => { d.status = "model_timeout"; },
  "rules-only carrying model identity": d => { d.mode = "rules_only"; d.status = "model_error"; },
  "wrong task": d => { d.task_id = 2; },
  "wrong issue": d => { d.issue_id = "issue-b"; },
  "wrong revision": d => { d.revision = 1; },
  "wrong full digest": d => { d.evidence_digest = "b".repeat(64); },
  "missing field": d => { delete d.explanation; },
  "known root cause claim": d => { d.uncertainty = "ROOT_CAUSE_CONFIRMED"; },
};
for (const [name, mutate] of Object.entries(invalid)) test("fail closed: " + name, async () => {
  const h = harness(), d = response(); mutate(d); const html = await success(h, "issue-a", d);
  assert.match(html, /Advice could not be verified/); assert.doesNotMatch(html, /Local AI ·|Rule-based only ·/);
});
test("all response text is escaped, with no active HTML/URL/image", async () => {
  const h = harness(), d = response(), payload = '<img src=x onerror="globalThis.pwned=1"> <script>alert(1)</script> & \' "';
  d.facts[0].label = d.facts[0].value = d.explanation = d.status_message = d.suggestions[0].text = payload;
  const html = await success(h, "issue-a", d);
  assert.doesNotMatch(html, /<img|<script|onerror="/); assert.match(html, /&lt;img/); assert.match(html, /&quot;/); assert.match(html, /&#39;/);
});
test("two simultaneous issues remain separate and double click does not duplicate", async () => {
  const h = harness(), a = h.controller.explain("issue-a"), duplicate = h.controller.explain("issue-a"), b = h.controller.explain("issue-b");
  await duplicate; assert.equal(h.calls.length, 2);
  h.calls[1].resolve(response("issue-b")); await b; assert.match(h.controller.render("issue-a"), /Requesting advice/);
  h.calls[0].resolve(response()); await a;
  assert.match(h.controller.render("issue-a"), /Finding issue-a/); assert.match(h.controller.render("issue-b"), /Finding issue-b/);
});
const stale = {
  "navigation A to B": h => { h.state.taskId = 2; h.state.hash = "#task/2"; },
  "navigation A to B to A": h => { h.state.token += 2; },
  "different view": h => { h.state.view = "history"; },
  "logout": h => { h.state.session = { username: null }; },
  "same account new session": h => { h.state.session = { username: "synthetic" }; },
  "new account": h => { h.state.session = { username: "another" }; },
  "refresh same binding": h => { h.state.task = structuredClone(h.state.task); },
  "new revision": h => { h.state.task.revision++; },
  "new digest": h => { h.state.task.evidence_digest = "b".repeat(64); },
  "cancelled task": h => { h.state.task.status = "cancelled"; },
  "issue removed by review": h => { h.state.task.issues = []; },
};
for (const [name, mutate] of Object.entries(stale)) test("late success and error discarded: " + name, async () => {
  for (const reject of [false, true]) {
    const h = harness(), pending = h.controller.explain("issue-a"); mutate(h);
    assert.equal(h.calls[0].guard.isCurrent(), false);
    if (reject) h.calls[0].reject(Object.assign(new Error("OLD PRIVATE RESPONSE"), { status: 409 })); else h.calls[0].resolve(response());
    await pending; const html = h.controller.render("issue-a");
    assert.doesNotMatch(html, /Local AI ·|OLD PRIVATE|task evidence has changed/);
  }
});
test("explicit invalidation aborts and prevents old response releasing newer pending state", async () => {
  const h = harness(), old = h.controller.explain("issue-a"); h.controller.invalidate();
  assert.equal(h.calls[0].guard.signal.aborted, true);
  const newer = h.controller.explain("issue-a"); h.calls[0].resolve(response()); await old;
  assert.match(h.controller.render("issue-a"), /Requesting advice/); assert.equal(h.calls[1].guard.isCurrent(), true);
  h.calls[1].resolve(response()); await newer;
});
for (const [status, message] of [[401, "session expired"], [403, "not permitted"], [404, "no longer available"], [409, "evidence has changed"], [500, "could not be retrieved"]]) {
  test("HTTP error " + status + " is not success", async () => {
    const h = harness(), pending = h.controller.explain("issue-a"); h.calls[0].reject(Object.assign(new Error("unsafe private server error"), { status })); await pending;
    const html = h.controller.render("issue-a"); assert.ok(html.includes(message)); assert.doesNotMatch(html, /unsafe private|Local AI ·/);
  });
}
test("bounded page wait has no automatic retry, and late success cannot replace timeout", async () => {
  const h = harness(), pending = h.controller.explain("issue-a"), timer = [...h.timers.values()][0];
  assert.equal(timer.ms, 60000); timer.fn(); assert.equal(h.calls[0].guard.signal.aborted, true);
  assert.match(h.controller.render("issue-a"), /timed out in the page/);
  h.calls[0].resolve(response()); await pending; assert.match(h.controller.render("issue-a"), /timed out in the page/); assert.equal(h.calls.length, 1);
});
for (const change of [h => h.state.task.status = "completed", h => h.state.task.evidence_digest = "short", h => h.state.task.revision = 0, h => h.state.task.issues.push({ id: "issue-a" })]) {
  test("ineligible task cannot request advice " + change.toString(), async () => { const h = harness(); change(h); await h.controller.explain("issue-a"); assert.equal(h.calls.length, 0); });
}
function apiHarness(fetch) {
  const source = fs.readFileSync(path.join(__dirname, "../product/static/app.js"), "utf8");
  const apiSource = source.slice(source.indexOf("async function api("), source.indexOf("const post ="));
  const sandbox = { fetch, FormData: class {}, S: { session: { username: "current" } }, renders: 0 };
  vm.createContext(sandbox); vm.runInContext("function render(){renders++};" + apiSource + ";globalThis.callApi=api;", sandbox);
  return sandbox;
}
test("actual API helper sends protected same-origin POST, not callback metadata", async () => {
  let sent; const a = apiHarness(async (url, options) => { sent = { url, options }; return { status: 200, ok: true, json: async () => response() }; });
  await a.callApi("/tasks/1/issues/issue-a/explanation", { method: "POST", body: JSON.stringify({ revision: 2, evidence_digest: digest }), isCurrent: () => true });
  assert.equal(sent.url, "/api/tasks/1/issues/issue-a/explanation"); assert.equal(sent.options.headers["X-Requested-With"], "FinanceFlow"); assert.equal(sent.options.isCurrent, undefined);
});
test("actual API helper discards stale 401 before it can sign out the new session", async () => {
  const a = apiHarness(async () => ({ status: 401, ok: false, json: async () => ({ detail: "expired" }) }));
  await assert.rejects(a.callApi("/tasks/1/issues/x/explanation", { isCurrent: () => false }), { name: "AbortError" });
  assert.equal(a.S.session.username, "current"); assert.equal(a.renders, 0);
});
test("actual API helper preserves 409 status and discards after delayed JSON", async () => {
  const a = apiHarness(async () => ({ status: 409, ok: false, json: async () => ({ detail: "changed" }) }));
  await assert.rejects(a.callApi("/tasks/1/issues/x/explanation", { isCurrent: () => true }), e => e.status === 409);
  let current = true; const json = deferred(), b = apiHarness(async () => ({ status: 200, ok: true, json: () => json.promise }));
  const pending = b.callApi("/tasks/1/issues/x/explanation", { isCurrent: () => current }); await Promise.resolve(); current = false; json.resolve(response());
  await assert.rejects(pending, { name: "AbortError" });
});

for (const selector of ["[data-issue]", "#select-findings"]) test("actual selection event discards in-flight advice: " + selector, async () => {
  const h = harness(), handlers = {};
  const source = fs.readFileSync(path.join(__dirname, "../product/static/app.js"), "utf8");
  const integration = source.slice(source.indexOf("const issueAdvice ="), source.indexOf("const go ="));
  const sandbox = { window: { FinanceIssueAdvice: { create: () => h.controller }, addEventListener() {} },
    document: { addEventListener: (type, callback) => { handlers[type] = callback; } } };
  vm.runInNewContext(integration, sandbox);
  const pending = h.controller.explain("issue-a");
  handlers.change?.({ target: { matches: value => value.split(",").map(s => s.trim()).includes(selector) } });
  assert.equal(h.calls[0].guard.signal.aborted, true);
  h.calls[0].resolve(response()); await pending;
  assert.doesNotMatch(h.controller.render("issue-a"), /Local AI ·/);
});
