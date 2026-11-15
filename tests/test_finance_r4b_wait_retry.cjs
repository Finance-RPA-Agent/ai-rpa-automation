"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// Reuse the existing navigation fixture. Install the real third module and a manual clock.
const source = path.join(__dirname, "../product/static");
const original = fs.readFileSync(path.join(__dirname, "assistant-navigation.cjs"), "utf8");
const firstScenario = original.indexOf('test("running -> Settings');
assert.ok(firstScenario > 0);
const clockVm = { ...vm, createContext(globals) {
  const timers = new Map();
  let next = 0;
  Object.assign(globals, { timers, AbortController,
    setTimeout(fn, ms) { timers.set(++next, {fn, ms}); return next; },
    clearTimeout(id) { timers.delete(id); },
  });
  const context = vm.createContext(globals);
  vm.runInContext(fs.readFileSync(path.join(source, "issue-advice.js"), "utf8"), context);
  return context;
}};
const fixture = vm.runInNewContext(original.slice(0, firstScenario) + "\ncreateHarness", {
  require: n => n === "node:vm" ? clockVm : require(n), console, URL, __dirname,
  process: {argv: ["node", "fixture", "--source", source]}, setImmediate, setTimeout, clearTimeout,
});
const evaluate = (h, s) => vm.runInContext(s, h.context);
const issue = "finding-a";
const digest = "a".repeat(64);
const explainPath = "/api/tasks/1/issues/" + issue + "/explanation";
const detailPath = "/api/tasks/1";
const detail = (id = 1) => ({id, code: "FF-0001", title: "Synthetic task", status: "waiting_confirmation",
  revision: 3, evidence_digest: digest, issues: [{id: issue, type: "amount_mismatch", message: "Compare the amounts.", can_correct: true}],
  issue_count: 1, decisions: [], records: [], trace: [], row_count: 1, archive_count: 0,
  source_sha256: digest, reference_sha256: digest, updated_at: "2026-11-04T00:00:00Z"});
function setTask(h, id = 1) {
  evaluate(h, "S.token++; S.id=" + id + "; S.route='task'; S.tab='review';location.hash='#task/" + id + "//review'; S.task=" + JSON.stringify(detail(id)) + "; issueAdvice.sync()");
}
async function app() {
  const h = fixture({hash: "#settings"});
  await h.ready();
  setTask(h);
  return h;
}
const panel = h => evaluate(h, 'issueAdvice.render("finding-a")');
const explain = h => evaluate(h, 'issueAdvice.explain("finding-a")');
const refresh = h => h.clickAction("refresh-advice-task", {issueId: issue});
const timer = (h, ms) => [...h.context.timers.values()].find(t => t.ms === ms);
const adviceCalls = h => h.posts(/\/explanation$/).length;
function pending(h) {
  const gate = h.hold("POST", explainPath);
  return {gate, done: h.clickAction("issue-advice", {issueId: issue})};
}
async function timedOut(h) {
  const p = pending(h);
  await p.gate.started;
  timer(h, 60000).fn();
  return p;
}
function answer(status = "advice_ready") {
  const local = status === "advice_ready";
  return {task_id: 1, issue_id: issue, revision: 3, evidence_digest: digest, mode: local ? "local_model" : "rules_only",
    model: local ? "qwen3.5:4b" : null, status, status_message: status, advisory_only: true,
    facts: [{id: "F_FINDING", source: "rule", label: "Rule finding", value: "Compare <amounts>"}],
    selected_fact_ids: ["F_FINDING"], uncertainty: "ROOT_CAUSE_UNKNOWN", explanation: "Root cause unknown.",
    suggestions: [{id: "KEEP_PENDING_REVIEW", text: "Keep pending", requires_human_decision: true}]};
}

test("G02 deadline blocks a direct second POST before a fresh task", async () => {
  const h = await app(), p = await timedOut(h);
  const count = adviceCalls(h);
  const again = explain(h);
  assert.equal(adviceCalls(h), count, "Direct retry sent a second POST after the page deadline");
  await again;
  p.gate.respond(200, answer()); await p.done;
  assert.match(panel(h), /timed out in the page/);
  assert.doesNotMatch(panel(h), /Local AI ·|Rule-based only/);
  assert.match(panel(h), /may still be running/);
  evaluate(h, "issueAdvice.invalidate()");
  await explain(h);
  assert.equal(adviceCalls(h), 1);
  assert.match(panel(h), /Refresh task/);
});

test("settings distinguishes unchecked, unreachable, missing and installed", async () => {
  const h = await app(), before = h.calls.length;
  for (const [model, label] of [[null, "Not checked"], [{available:false, installed:false}, "Service unreachable"],
    [{available:true, installed:false}, "Model missing"], [{available:true, installed:true}, "Installed"]]) {
    const html = evaluate(h, "S.model=" + JSON.stringify(model) + ";settingsPage()");
    assert.ok(html.includes(">" + label + "<"), label);
    assert.doesNotMatch(html, />Ready</);
  }
  assert.equal(h.calls.length, before);
});

test("slow notice, rule facts and manual retries share only the current binding", async () => {
  const h = await app(), p = pending(h);
  await p.gate.started;
  assert.deepEqual(Object.keys(h.calls.at(-1).body).sort(), ["evidence_digest","revision"]);
  await explain(h);
  assert.equal(adviceCalls(h), 1);
  assert.match(panel(h), /First use can take longer/);
  timer(h, 10000).fn();
  assert.match(panel(h), /Still waiting/);
  assert.doesNotMatch(panel(h), /\d+%|Rule-based only/);
  p.gate.respond(200, answer("model_busy")); await p.done;
  const retry = pending(h); await retry.gate.started;
  assert.match(panel(h), /Previous rule result/);
  assert.match(panel(h), /Compare &lt;amounts&gt;/);
  assert.match(panel(h), /Human decision required/);
  retry.gate.fail(new Error("synthetic network failure")); await retry.done;
  assert.match(panel(h), /could not be retrieved/); assert.match(panel(h), /Previous rule result/);
  const third = pending(h); await third.gate.started;
  third.gate.respond(200, answer()); await third.done;
  assert.match(panel(h), /Local AI ·/); assert.doesNotMatch(panel(h), /Previous rule result/);
  assert.equal(adviceCalls(h), 3);
  assert.equal(timer(h, 10000), undefined); assert.equal(timer(h, 60000), undefined);
});

test("timeout recovery GET is explicit, guarded and never retries by itself", async () => {
  const h = await app(), late = await timedOut(h);
  const start = h.calls.length;
  const failed = h.hold("GET", detailPath), attempt = refresh(h); await failed.started;
  await explain(h); await refresh(h);
  failed.respond(503, {}); await attempt;
  assert.match(panel(h), /could not be refreshed/i);
  await explain(h);
  const again = h.hold("GET", detailPath), get = refresh(h); await again.started;
  again.respond(200, detail()); await get;
  assert.deepEqual(Array.from(h.calls.slice(start), c => [c.method, c.url]), [["GET",detailPath],["GET",detailPath]]);
  assert.match(h.html(), /Synthetic task/); assert.match(h.html(), /Review correction/);
  assert.doesNotMatch(panel(h), /Refresh task/); assert.equal(adviceCalls(h), 1);
  const retry = pending(h); await retry.gate.started;
  late.gate.respond(401, {}); await late.done;
  assert.equal(h.state().sessionUsername, "Fixture Owner");
  assert.ok(timer(h, 60000)); assert.match(panel(h), /Requesting advice/);
  retry.gate.respond(200, answer()); await retry.done;
  assert.equal(adviceCalls(h), 2);
  console.log("deadline recovery GETs=2 (503,200); explanation POSTs=2 (initial, manual retry)");
});

for (const [transition, status] of [["another task",200],["settings",503],["new login",401],["selection",200]]) {
  test("late refresh is discarded after " + transition, async () => {
    const h = await app(), late = await timedOut(h);
    late.gate.respond(200, answer()); await late.done;
    const gate = h.hold("GET", detailPath), get = refresh(h); await gate.started;
    if (transition === "another task") setTask(h, 2);
    if (transition === "settings") await h.navigate("#settings");
    if (transition === "new login") { await h.clickAction("logout"); h.context.location.hash="#settings"; await h.login("Fixture Owner"); }
    if (transition === "selection") await h.clickAction("tab", {tab:"review"});
    const previous = evaluate(h, "S.task");
    gate.respond(status, {...detail(), title:"stale refresh"}); await get;
    assert.equal(evaluate(h, "S.task"), previous);
    assert.equal(h.state().sessionUsername, "Fixture Owner");
    assert.equal(adviceCalls(h), 1);
    if (transition === "selection") { await explain(h); assert.equal(adviceCalls(h),1); }
  });
}

for (const status of [403,404,409]) {
  test("reject stale rule evidence on HTTP " + status, async () => {
    const h = await app(), p = pending(h); await p.gate.started;
    p.gate.respond(200, answer("model_timeout")); await p.done;
    const retry = pending(h); await retry.gate.started;
    retry.gate.respond(status, {}); await retry.done;
    assert.doesNotMatch(panel(h), /Rule-based only|Previous rule result/);
    await explain(h); assert.equal(adviceCalls(h), 2);
  });
}
for (const status of ["unsupported","insufficient_evidence"]) {
  test("unusable evidence requests verification for " + status, async () => {
    const h = await app(), p = pending(h); await p.gate.started;
    p.gate.respond(200, answer(status)); await p.done;
    assert.match(panel(h), /verify|reimport/i); assert.doesNotMatch(panel(h), /Request advice again/);
    await explain(h); assert.equal(adviceCalls(h), 1);
  });
}


test("a rejected task snapshot keeps the gate until a real GET supplies the new binding", async () => {
  const h = await app(), p = await timedOut(h);
  p.gate.respond(200, answer()); await p.done;
  const wrong = h.hold("GET", detailPath), first = refresh(h); await wrong.started;
  wrong.respond(200, detail(2)); await first;
  assert.equal(h.state().taskId, 1); await explain(h); assert.equal(adviceCalls(h), 1);
  const ok = h.hold("GET", detailPath), second = refresh(h); await ok.started;
  const updated = {...detail(), revision: 4, evidence_digest: "b".repeat(64)};
  ok.respond(200, updated); await second;
  const manual = pending(h); await manual.gate.started;
  const body = h.calls.at(-1).body;
  assert.equal(body.revision, 4); assert.equal(body.evidence_digest, updated.evidence_digest);
  manual.gate.respond(200, answer()); await manual.done;
  assert.match(panel(h), /could not be verified/);
});

for (const change of [{issues: []}, {status: "cancelled"}, {evidence_digest: "short"}]) {
  test("GET cannot re-enable an ineligible binding: " + Object.keys(change)[0], async () => {
    const h = await app(), p = await timedOut(h);
    p.gate.respond(200, answer()); await p.done;
    const gate = h.hold("GET", detailPath), get = refresh(h); await gate.started;
    gate.respond(200, {...detail(), ...change}); await get;
    await explain(h);
    assert.equal(panel(h), ""); assert.equal(adviceCalls(h), 1);
  });
}
test("current refresh 401 clears the signed-in session", async () => {
  const h = await app(), late = await timedOut(h);
  const gate = h.hold("GET", detailPath), get = refresh(h); await gate.started;
  gate.respond(401, {}); await get; late.gate.respond(200, answer()); await late.done;
  assert.equal(h.state().sessionUsername, null);
  assert.equal(panel(h), ""); assert.equal(adviceCalls(h), 1);
});

test("unrenderable GET detail preserves the original refresh gate and selection", async () => {
  const h = await app(), p = await timedOut(h);
  p.gate.respond(200, answer()); await p.done;
  evaluate(h, "S.selected.add('finding-a')");
  const previous = evaluate(h, "S.task");
  const gate = h.hold("GET", detailPath), get = refresh(h); await gate.started;
  gate.respond(200, {...detail(), source_sha256:null}); await get;
  assert.equal(evaluate(h, "S.task"), previous);
  assert.ok(evaluate(h, "S.selected.has('finding-a')"));
  assert.match(evaluate(h, "document.getElementById('toast').textContent"), /could not be refreshed/);
  assert.match(panel(h), /Refresh task/);
  await explain(h); assert.equal(adviceCalls(h), 1);
});
