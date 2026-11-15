"use strict";
// Execute the actual UI with the existing navigation fixture and controlled HTTP.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = path.join(__dirname, "../product/static");
const original = fs.readFileSync(path.join(__dirname, "assistant-navigation.cjs"), "utf8");
const first = original.indexOf('test("running -> Settings');
assert.ok(first > 0);
const hookedVm = {...vm, createContext(globals) {
  globals.__handlers = {};
  globals.__intervals = [];
  const add = globals.document.addEventListener;
  globals.document.addEventListener = (name, fn) => {
    (globals.__handlers[name] ||= []).push(fn); add(name, fn);
  };
  const interval = globals.setInterval;
  globals.setInterval = fn => { globals.__intervals.push(fn); return interval(fn); };
  return vm.createContext(globals);
}};
const fixture = vm.runInNewContext(original.slice(0, first) + "\ncreateHarness", {
  require: n => n === "node:vm" ? hookedVm : require(n), console, URL, __dirname,
  process: {argv: ["node", "fixture", "--source", source]}, setImmediate, setTimeout, clearTimeout,
});
const evaluate = (h, s) => vm.runInContext(s, h.context);
const task = {id: 42, title: "Test reconciliation", code: "FF-00042", status: "running", stage: "Validate and compare",
  plan_status: "ready", plan: null, row_count: 2, archive_count: 0, issue_count: 0, revision: 1,
  source_sha256: "a".repeat(64), reference_sha256: "b".repeat(64), records: [], issues: [], decisions: [], events: [], trace: []};
const running = () => ({id: 7, title: "Test chat", folder: "/input", bi_folder: "/bi", active_turn: 11,
  files: [], charts: [], artifacts: [], preview: null,
  turns: [{id: 11, instruction: "Analyze data", status: "running", steps: [], progress: {phase: "planning"}}]});
async function app(options = {}) { const h = fixture({hash: "#assistant", ...options}); await h.ready(); return h; }
function submitTask(h) {
  return evaluate(h, '__handlers.submit[__handlers.submit.length-1]({preventDefault(){},target:{id:"task-form",querySelector(){return null;}}})');
}

test("a task example fills an editable request without executing or changing folders", async () => {
  const h = await app();
  h.input("assistant-folder", "/chosen/input"); h.input("assistant-bi-folder", "/chosen/bi");
  await h.clickAction("assistant-example", {example: "count"});
  assert.match(h.state().draft, /without grouping/);
  assert.equal(evaluate(h, "A.folder"), "/chosen/input");
  assert.equal(evaluate(h, "A.biFolder"), "/chosen/bi");
  assert.equal(h.posts(/./).length, 0);
  h.input("assistant-request", "My edited request");
  assert.equal(h.state().draft, "My edited request");
  await h.clickAction("assistant-example", {example: "reconcile"});
  assert.match(h.state().draft, /without automatically applying corrections/);
});

test("examples cannot replace the draft during an active request", async () => {
  const h = await app({hash: "#assistant/7", details: {7: running()}});
  evaluate(h, 'A.draft="Do not replace"');
  await h.clickAction("assistant-example", {example: "quality"});
  assert.equal(h.state().draft, "Do not replace");
  assert.equal(h.posts(/./).length, 0);
});

test("progress shows real stages, saved operations and a long model wait", async () => {
  const h = await app({hash: "#assistant/7", details: {7: running()}});
  evaluate(h, `A.chat.turns[0].created_at=new Date(Date.now()-20000).toISOString();
    A.chat.turns[0].progress={phase:"waiting_model",since:new Date(Date.now()-20000).toISOString()};
    A.chat.turns[0].steps=[{tool:"list_files",status:"success"},{tool:"aggregate",status:"error",error:"Retry needed"}];render()`);
  assert.match(h.html(), /Waiting for the local model/);
  assert.match(h.html(), /1 completed operations/);
  assert.match(h.html(), /taking longer/);
  assert.match(h.html(), /20s elapsed/);
  assert.doesNotMatch(h.html(), /\d+%/);
  evaluate(h, 'A.chat.turns[0].progress={phase:"tool",tool:"export_report"};render()');
  assert.match(h.html(), /Running: Create Excel report/);
  assert.doesNotMatch(h.html(), /taking longer/);
  evaluate(h, 'A.chat.turns[0].cancel_requested=true;render()');
  assert.match(h.html(), /Stop requested/);
  assert.match(h.html(), /may need to finish/);
});

test("failed polling preserves results and refresh reads status without submitting work", async () => {
  const h = await app({hash: "#assistant/7", details: {7: running()}});
  const gate = h.hold("GET", "/api/assistant/chats/7");
  const pending = h.assistantPoll(); await gate.started;
  gate.respond(503, {detail: "Temporary outage"}); await pending;
  assert.match(h.html(), /Unable to refresh progress/);
  assert.match(h.html(), /last saved result/);
  assert.equal(h.state().chatId, 7);
  await h.clickAction("assistant-refresh");
  assert.doesNotMatch(h.html(), /Unable to refresh progress/);
  assert.equal(h.posts(/./).length, 0);
});

test("a late polling error cannot overwrite another page", async () => {
  const h = await app({hash: "#assistant/7", details: {7: running()}});
  const gate = h.hold("GET", "/api/assistant/chats/7");
  const pending = h.assistantPoll(); await gate.started;
  await h.navigate("#settings");
  gate.respond(503, {detail: "Old outage"}); await pending;
  assert.doesNotMatch(h.html(), /Old outage|Unable to refresh progress/);
});

test("default reconciliation uses one start request and prevents duplicate clicks", async () => {
  const h = await app({hash: "#new"});
  evaluate(h, 'S.draft.source_id="source";S.draft.reference_id="reference"');
  assert.match(h.html(), /Start reconciliation/);
  assert.doesNotMatch(h.html(), /id="task-instruction"/);
  const gate = h.hold("POST", "/api/tasks/quick-start");
  const first = submitTask(h); await gate.started;
  await submitTask(h);
  assert.equal(h.posts(/quick-start/).length, 1);
  const body = h.posts(/quick-start/)[0].body;
  assert.deepEqual(JSON.parse(JSON.stringify(body)), {title: "Supplier order reconciliation", source_id: "source", reference_id: "reference"});
  gate.respond(201, task); await first;
  assert.equal(h.location(), "#task/42");
  assert.equal(h.posts(/\/(plan|run)$/).length, 0);
});

test("advanced mode retains explicit plan review and valid legacy API shape", async () => {
  const h = await app({hash: "#new"});
  evaluate(h, 'S.draft.review_plan=true;S.draft.source_id="source";S.draft.reference_id="reference";render()');
  assert.match(h.html(), /id="task-instruction"/);
  const gate = h.hold("POST", "/api/tasks");
  const pending = submitTask(h); await gate.started;
  assert.equal(h.posts(/^\/api\/tasks$/)[0].body.review_plan, undefined);
  gate.respond(201, {...task, status: "pending"}); await pending;
  assert.equal(h.posts(/quick-start|\/(plan|run)$/).length, 0);
});

test("start failure remains actionable on the form and never silently retries", async () => {
  const h = await app({hash: "#new"});
  const gate = h.hold("POST", "/api/tasks/quick-start");
  const pending = submitTask(h); await gate.started;
  gate.respond(409, {detail: "Another task is using the local worker."}); await pending;
  assert.equal(h.location(), "#new");
  assert.equal(evaluate(h, "S.startBusy"), false);
  assert.match(evaluate(h, "S.startError"), /Another task/);
  assert.equal(h.posts(/./).length, 1);
});

test("task status refresh is read-only and clears the stale-state banner", async () => {
  const h = await app();
  evaluate(h, `S.route="task";S.id=42;S.task=${JSON.stringify(task)};render()`);
  const gate = h.hold("GET", "/api/tasks/42");
  const pending = evaluate(h, "__intervals[__intervals.length-1]()"); await gate.started;
  gate.respond(503, {detail: "Temporary outage"}); await pending;
  assert.match(h.html(), /Unable to refresh progress/);
  const refresh = h.hold("GET", "/api/tasks/42");
  const done = h.clickAction("refresh-task"); await refresh.started;
  refresh.respond(200, task); await done;
  assert.doesNotMatch(h.html(), /Unable to refresh progress/);
  assert.match(h.html(), /Validate and compare/);
  assert.equal(h.posts(/./).length, 0);
});
