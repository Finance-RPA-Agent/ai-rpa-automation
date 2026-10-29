// Data assistant navigation and asynchronous-state regression.
// Run: node tests/assistant-navigation.cjs
// Uses only Node built-ins and synthetic DOM/API fixtures. No server, model,
// browser, account or real data is accessed. --source supports a baseline comparison;
// --out optionally writes a JSON result to an explicitly supplied path.
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const sourceArg = process.argv.indexOf("--source");
const source = sourceArg > -1 ? process.argv[sourceArg + 1] : path.resolve(__dirname, "../product/static");
const outArg = process.argv.indexOf("--out");
const outFile = outArg > -1 ? process.argv[outArg + 1] : null;

const clone = value => JSON.parse(JSON.stringify(value));
const flush = async (rounds = 8) => {
  for (let index = 0; index < rounds; index += 1) await new Promise(resolve => setImmediate(resolve));
};

function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return {promise, resolve, reject};
}

function fixtureTurn(id, options = {}) {
  const turn = {
    id,
    instruction: options.instruction || `Synthetic request ${id}`,
    status: options.status || "running",
    steps: options.steps || [],
    message: options.message || "",
    error: options.error === undefined ? null : options.error,
  };
  if (options.can_retry !== undefined) turn.can_retry = options.can_retry;
  if (options.workflow) turn.workflow = options.workflow;
  if (options.batch_id) turn.batch_id = options.batch_id;
  if (options.review_batch) turn.review_batch = options.review_batch;
  return turn;
}

function fixtureChat(id, options = {}) {
  return {
    id,
    title: options.title || `Conversation ${id}`,
    folder: `/fixtures/inbox-${id}`,
    bi_folder: options.bi_folder === undefined ? `/fixtures/bi-${id}` : options.bi_folder,
    active_turn: options.active_turn === undefined ? null : options.active_turn,
    files: options.files || [],
    preview: options.preview === undefined ? null : options.preview,
    charts: options.charts || [],
    artifacts: options.artifacts || [],
    turns: options.turns || [],
  };
}

function runningChat(id, turnId, title) {
  return fixtureChat(id, {
    title: title || `Running conversation ${id}`,
    active_turn: turnId,
    turns: [fixtureTurn(turnId, {status: "running", instruction: `Reconcile synthetic input for ${id}`})],
  });
}

function reviewBatch() {
  return {
    id: 5, code: "BATCH-00005", status: "waiting_confirmation",
    input_rows: 10, matched_rows: 7, unresolved_rows: 3, archive_receipts: 0,
    review_tasks: [{job_id: 42, status: "waiting_confirmation"}],
    report_available: false, attention: [], busy: false, error: null,
  };
}

function reviewChat(id, turnId) {
  return fixtureChat(id, {
    title: `Review conversation ${id}`,
    active_turn: null,
    turns: [fixtureTurn(turnId, {
      status: "waiting_confirmation",
      instruction: "Reconcile and pause for review",
      workflow: "reconciliation_review",
      batch_id: 5,
      review_batch: reviewBatch(),
      message: "7 of 10 input rows completed automatically; 3 rows remain unresolved.",
      can_retry: false,
    })],
  });
}

function completedChat(id, turnId, title) {
  return fixtureChat(id, {
    title: title || `Completed conversation ${id}`,
    active_turn: null,
    turns: [fixtureTurn(turnId, {
      status: "completed",
      instruction: "Complete the synthetic reconciliation",
      message: "Reconciliation complete: 3 of 3 input rows are reconciled.",
      can_retry: false,
    })],
  });
}

function failedChat(id, turnId, title) {
  return fixtureChat(id, {
    title: title || `Failed conversation ${id}`,
    active_turn: null,
    turns: [fixtureTurn(turnId, {
      status: "failed",
      instruction: "Attempt the synthetic reconciliation",
      error: "The local model returned an invalid action.",
      can_retry: true,
    })],
  });
}

function cancelledChat(id, turnId, title) {
  return fixtureChat(id, {
    title: title || `Cancelled conversation ${id}`,
    active_turn: null,
    turns: [fixtureTurn(turnId, {
      status: "cancelled",
      instruction: "Stop the synthetic reconciliation",
      message: "Stopped at a tool boundary. Existing results and reports were retained.",
      can_retry: true,
    })],
  });
}

function createHarness(options) {
  const fixture = {
    session: {username: "Fixture Owner", setup_required: false},
    chats: clone(options.chats || []),
    details: clone(options.details || {}),
    nextChatId: options.nextChatId || 20,
    nextTurnId: options.nextTurnId || 30,
  };
  const calls = [];
  const elements = new Map();
  const intervals = [];
  const documentHandlers = {};
  const windowHandlers = {};
  const holds = [];
  let hash = options.hash || "#dashboard";
  const location = {};
  Object.defineProperty(location, "hash", {
    enumerable: true,
    get: () => hash,
    set: value => { hash = String(value).startsWith("#") ? String(value) : `#${value}`; },
  });
  const history = {
    replaceState(_state, _title, url) {
      if (typeof url === "string" && url.startsWith("#")) hash = url;
    },
  };
  const response = (status, body) => ({
    status,
    ok: status >= 200 && status < 300,
    headers: {get: () => null},
    json: async () => clone(body),
  });
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      id, innerHTML: "", textContent: "", className: "", value: "", disabled: false,
      remove() {}, focus() {}, append() {}, click() {},
    });
    return elements.get(id);
  };
  const findHold = (method, url) => holds.find(hold => !hold.used && hold.method === method && hold.url === url);
  async function fetch(url, fetchOptions = {}) {
    const method = (fetchOptions.method || "GET").toUpperCase();
    let body = null;
    if (typeof fetchOptions.body === "string") {
      try { body = JSON.parse(fetchOptions.body); } catch { body = fetchOptions.body; }
    }
    calls.push({url, method, body});
    const held = findHold(method, url);
    if (held) {
      held.used = true;
      held.start();
      return held.promise;
    }
    if (url === "/api/session") return response(200, fixture.session);
    if (url === "/api/tasks") return response(200, {tasks: [], active_task: null});
    if (url === "/api/files") return response(200, {files: []});
    if (url === "/api/commands") return response(200, {commands: []});
    if (url === "/api/model") return response(200, {installed: true, model: "fixture", message: "Fixture only"});
    if (url === "/api/logout") return response(200, {ok: true});
    if (url === "/api/login" && method === "POST") {
      fixture.session = {username: body?.username || "Fixture Owner", setup_required: false};
      return response(200, fixture.session);
    }
    if (url === "/api/assistant/chats" && method === "GET") return response(200, {chats: fixture.chats});
    if (url === "/api/assistant/chats" && method === "POST") {
      const id = fixture.nextChatId++;
      const chat = fixtureChat(id, {title: body?.title || `Created conversation ${id}`});
      chat.folder = body?.folder || chat.folder;
      chat.bi_folder = body?.bi_folder ?? null;
      fixture.chats.unshift({id, title: chat.title});
      fixture.details[id] = chat;
      return response(201, chat);
    }
    const detailMatch = /^\/api\/assistant\/chats\/(\d+)$/.exec(url);
    if (detailMatch && method === "GET") {
      const id = Number(detailMatch[1]);
      if (!fixture.details[id]) return response(404, {detail: "Conversation was not found."});
      return response(200, fixture.details[id]);
    }
    const turnMatch = /^\/api\/assistant\/chats\/(\d+)\/turns$/.exec(url);
    if (turnMatch && method === "POST") {
      const chatId = Number(turnMatch[1]);
      const turnId = fixture.nextTurnId++;
      const chat = fixture.details[chatId];
      if (chat) {
        chat.active_turn = turnId;
        chat.turns.push(fixtureTurn(turnId, {status: "running", instruction: body?.instruction || "Synthetic follow-up"}));
      }
      return response(202, {id: turnId, chat_id: chatId, status: "running"});
    }
    return response(404, {detail: `Unexpected fixture request: ${method} ${url}`});
  }

  const context = vm.createContext({
    console, FormData: class {}, URL, Intl,
    setTimeout: () => 0, clearTimeout() {},
    setInterval: callback => { intervals.push(callback); return intervals.length; },
    clearInterval() {},
    location, history,
    window: {
      addEventListener: (type, handler) => { windowHandlers[type] = handler; },
      scrollTo() {},
    },
    document: {
      getElementById: element,
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener: (type, handler) => { (documentHandlers[type] ||= []).push(handler); },
      createElement: () => ({href: "", download: "", click() {}, remove() {}}),
      body: {append() {}},
    },
    fetch,
  });
  for (const name of ["assistant.js", "app.js"]) {
    vm.runInContext(fs.readFileSync(path.join(source, name), "utf8"), context, {filename: name});
  }

  function hold(method, url) {
    const gate = deferred();
    const started = deferred();
    holds.push({
      method: method.toUpperCase(), url, promise: gate.promise, used: false,
      start: () => started.resolve(),
      respond: (status, body) => gate.resolve(response(status, body)),
      fail: error => gate.reject(error),
    });
    return {started: started.promise, respond: (status, body) => gate.resolve(response(status, body)), fail: error => gate.reject(error)};
  }

  async function ready() { await flush(12); }

  const snapshots = [];
  let requestCursor = 0;

  function state() {
    return vm.runInContext(`({
      route: S.route, id: S.id, token: S.token,
      chatId: A.chat?.id ?? null, activeTurn: A.chat?.active_turn ?? null,
      taskId: S.task?.id ?? null, batchId: S.batch?.id ?? null,
      contextBatch: S.contextBatch ?? null,
      historyIds: A.chats.map(item => item.id),
      draft: A.draft, error: A.error, busy: A.busy,
      selectedId: A.selectedId ?? null, epoch: A.epoch ?? null,
      sessionEpoch: S.sessionEpoch ?? null, sessionUsername: S.session?.username ?? null,
      hash: location.hash
    })`, context);
  }

  function html() { return element("app").innerHTML; }

  function uiFlags() {
    const markup = html();
    return {
      working: /Working locally/.test(markup),
      reviewEntry: /#task\/\d+\/\d+\/review/.test(markup),
      newEntry: /What would you like to do with your data\?/.test(markup),
      settings: /Workspace settings/.test(markup),
      errorPage: /Unable to open this view/.test(markup),
      retry: /Retry request/.test(markup),
    };
  }

  function record(label) {
    const requests = calls.slice(requestCursor);
    requestCursor = calls.length;
    snapshots.push({label, state: state(), ui: uiFlags(), requests});
  }

  function evidence() {
    return {snapshots, calls: calls.slice()};
  }

  async function navigate(target) {
    record(`before navigate ${target}`);
    location.hash = target;
    try {
      await vm.runInContext("navigate()", context);
      await flush();
    } finally {
      record(`after navigate ${target}`);
    }
  }

  async function clickAction(action, dataset = {}) {
    record(`before click ${action}`);
    const target = {
      disabled: false,
      dataset: {action, ...dataset},
      closest(selector) { return selector === "[data-action]" ? target : null; },
    };
    const event = {target: {closest: selector => selector === "[data-action]" ? target : null}};
    for (const handler of documentHandlers.click || []) await handler(event);
    await flush();
    record(`after click ${action}`);
  }

  function input(id, value) {
    element(id).value = value;
    for (const handler of documentHandlers.input || []) handler({target: {id, value}});
    record(`input ${id}`);
  }

  function submit() {
    record("before assistant submit");
    const form = {id: "assistant-form", querySelector: () => null};
    const event = {preventDefault() {}, target: form};
    return Promise.all((documentHandlers.submit || []).map(handler => handler(event)))
      .then(result => {
        record("after assistant submit");
        return result;
      });
  }

  async function login(username = "Second Fixture Owner") {
    record(`before login ${username}`);
    element("username").value = username;
    element("password").value = "fixture-password";
    const form = {id: "auth-form", querySelector: () => null};
    const event = {preventDefault() {}, target: form};
    await Promise.all((documentHandlers.submit || []).map(handler => handler(event)));
    await flush();
    record(`after login ${username}`);
  }

  async function change(id, value) {
    record(`before change ${id}`);
    const target = {id, value, dataset: {}};
    for (const handler of documentHandlers.change || []) await handler({target});
    await flush();
    record(`after change ${id}`);
  }

  async function assistantPoll() {
    record("before assistant poll");
    if (intervals[0]) await intervals[0]();
    await flush();
    record("after assistant poll");
  }

  function assistantHref() {
    const match = /<a href="([^"]*)" title="Data assistant"/.exec(html());
    return match ? match[1] : null;
  }

  function addChat(chat) {
    fixture.details[chat.id] = chat;
    if (!fixture.chats.some(item => item.id === chat.id)) fixture.chats.unshift({id: chat.id, title: chat.title});
  }

  function updateChat(chat) { fixture.details[chat.id] = chat; }

  function detailCalls(id) {
    return calls.filter(call => call.method === "GET" && call.url === `/api/assistant/chats/${id}`).length;
  }

  function posts(pattern) {
    return calls.filter(call => call.method === "POST" && pattern.test(call.url));
  }

  const api = {
    context, calls, fixture, hold, ready, navigate, clickAction, input, submit, login, change, assistantPoll,
    state, html, assistantHref, addChat, updateChat, detailCalls, posts, record, evidence,
    location: () => location.hash,
  };
  testHarnesses.push({test: activeTestName, api});
  return api;
}

const testHarnesses = [];
let activeTestName = "";
const tests = [];
function test(name, run) { tests.push({name, run}); }


test("running -> Settings -> sidebar back keeps the same chat, turn and polling target", async () => {
  const harness = createHarness({
    hash: "#assistant/7",
    chats: [{id: 9, title: "Other newest conversation"}, {id: 8, title: "Another conversation"}, {id: 7, title: "Running conversation 7"}],
    details: {7: runningChat(7, 11), 8: runningChat(8, 81), 9: runningChat(9, 91)},
  });
  await harness.ready();
  let state = harness.state();
  assert.equal(state.route, "assistant");
  assert.equal(state.id, 7);
  assert.equal(state.chatId, 7);
  assert.equal(state.activeTurn, 11);
  assert.match(harness.html(), /Working locally/);

  await harness.navigate("#settings");
  assert.equal(harness.state().route, "settings");
  const href = harness.assistantHref();
  assert.ok(href, "sidebar Data assistant link must exist");
  await harness.navigate(href);

  state = harness.state();
  assert.equal(state.route, "assistant");
  assert.equal(state.id, 7, "route ID must be restored");
  assert.equal(state.chatId, 7, "A.chat must be the same conversation");
  assert.equal(state.activeTurn, 11, "active turn must still be visible");
  assert.equal(state.hash, "#assistant/7", "route and chat ID must stay consistent");
  assert.match(harness.html(), /Working locally/);
  assert.equal(state.historyIds[0], 9, "history's newest item is deliberately another chat");

  const detailBefore = harness.detailCalls(7);
  await harness.assistantPoll();
  assert.equal(harness.detailCalls(7), detailBefore + 1, "polling must read chat 7");
  assert.equal(harness.state().chatId, 7);
  assert.equal(harness.posts(/\/turns$/).length, 0, "navigation or polling must not submit a turn");
  assert.equal(harness.calls.filter(call => call.method === "DELETE" || /cancel/.test(call.url)).length, 0);
});

test("waiting for review -> Settings -> back keeps the review entry", async () => {
  const harness = createHarness({
    hash: "#assistant/12",
    chats: [{id: 12, title: "Review conversation 12"}],
    details: {12: reviewChat(12, 15)},
  });
  await harness.ready();
  assert.equal(harness.state().chatId, 12);
  assert.match(harness.html(), /Needs review/);
  await harness.navigate("#settings");
  await harness.navigate(harness.assistantHref());
  const state = harness.state();
  assert.equal(state.id, 12);
  assert.equal(state.chatId, 12);
  assert.equal(harness.html().includes("#task/42/5/review"), true, "review link must be restored");
  assert.match(harness.html(), /Needs review/);
});

test("completed while away -> back reads the final state, not stale progress", async () => {
  const harness = createHarness({
    hash: "#assistant/7",
    chats: [{id: 7, title: "Running conversation 7"}],
    details: {7: runningChat(7, 11)},
  });
  await harness.ready();
  await harness.navigate("#settings");
  harness.updateChat(completedChat(7, 11));
  await harness.navigate(harness.assistantHref());
  const state = harness.state();
  assert.equal(state.chatId, 7);
  assert.equal(state.activeTurn, null);
  assert.doesNotMatch(harness.html(), /Working locally/);
  assert.match(harness.html(), /Reconciliation complete: 3 of 3 input rows/);
});

test("failed while away -> back shows the failure and retry entry", async () => {
  const harness = createHarness({
    hash: "#assistant/13",
    chats: [{id: 13, title: "Running conversation 13"}],
    details: {13: runningChat(13, 16)},
  });
  await harness.ready();
  await harness.navigate("#settings");
  harness.updateChat(failedChat(13, 16));
  await harness.navigate(harness.assistantHref());
  const state = harness.state();
  assert.equal(state.chatId, 13);
  assert.equal(state.activeTurn, null);
  assert.doesNotMatch(harness.html(), /Working locally/);
  assert.match(harness.html(), /The local model returned an invalid action\./);
  assert.match(harness.html(), /Retry request/);
});

test("cancelled while away -> back shows the retained-result state", async () => {
  const harness = createHarness({
    hash: "#assistant/14",
    chats: [{id: 14, title: "Running conversation 14"}],
    details: {14: runningChat(14, 17)},
  });
  await harness.ready();
  await harness.navigate("#settings");
  harness.updateChat(cancelledChat(14, 17));
  await harness.navigate(harness.assistantHref());
  const state = harness.state();
  assert.equal(state.chatId, 14);
  assert.equal(state.activeTurn, null);
  assert.doesNotMatch(harness.html(), /Working locally/);
  assert.match(harness.html(), /Stopped at a tool boundary\. Existing results and reports were retained\./);
  assert.match(harness.html(), /Retry request/);
});

test("a stale polling response cannot overwrite a later conversation choice", async () => {
  const harness = createHarness({
    hash: "#assistant/7",
    chats: [{id: 8, title: "Conversation 8"}, {id: 7, title: "Conversation 7"}],
    details: {7: runningChat(7, 11), 8: runningChat(8, 81)},
  });
  await harness.ready();
  const gate = harness.hold("GET", "/api/assistant/chats/7");
  const polling = harness.assistantPoll();
  await gate.started;
  await harness.navigate("#assistant/8");
  assert.equal(harness.state().chatId, 8);
  gate.respond(200, runningChat(7, 11, "Stale polling copy of 7"));
  await polling;
  await harness.ready();
  const state = harness.state();
  assert.equal(state.id, 8);
  assert.equal(state.chatId, 8);
  assert.equal(state.activeTurn, 81);
  assert.doesNotMatch(harness.html(), /Stale polling copy of 7/);
});

test("explicit New conversation keeps its blank selection and in-page draft", async () => {
  const harness = createHarness({
    hash: "#assistant/7",
    chats: [{id: 7, title: "Running conversation 7"}],
    details: {7: runningChat(7, 11)},
  });
  await harness.ready();
  await harness.clickAction("assistant-new");
  await harness.navigate("#assistant");
  let state = harness.state();
  assert.equal(state.route, "assistant");
  assert.equal(state.chatId, null);
  assert.equal(state.selectedId, null);
  harness.input("assistant-request", "Draft only, do not submit");
  await harness.navigate("#settings");
  await harness.navigate(harness.assistantHref());
  state = harness.state();
  assert.equal(state.chatId, null, "New conversation must not be replaced by the old chat");
  assert.equal(state.draft, "Draft only, do not submit");
  assert.match(harness.html(), /Draft only, do not submit/);
  assert.equal(harness.posts(/\/turns$/).length, 0);
});

test("A/B switch with a delayed older response: old success cannot overwrite B", async () => {
  const harness = createHarness({
    hash: "#assistant/7",
    chats: [{id: 9, title: "Conversation 9"}, {id: 8, title: "Conversation 8"}, {id: 7, title: "Conversation 7"}],
    details: {7: runningChat(7, 11), 8: runningChat(8, 81), 9: runningChat(9, 91)},
  });
  await harness.ready();
  const gate = harness.hold("GET", "/api/assistant/chats/8");
  const older = harness.navigate("#assistant/8");
  await gate.started;
  await harness.navigate("#assistant/9");
  assert.equal(harness.state().chatId, 9);
  gate.respond(200, runningChat(8, 81));
  await older;
  await harness.ready();
  const state = harness.state();
  assert.equal(state.route, "assistant");
  assert.equal(state.id, 9);
  assert.equal(state.chatId, 9, "stale chat 8 response must not replace selected chat 9");
  assert.equal(state.activeTurn, 91);
});

test("selecting B then leaving before its detail returns still restores B", async () => {
  const harness = createHarness({
    hash: "#assistant/7",
    chats: [{id: 8, title: "Conversation 8"}, {id: 7, title: "Conversation 7"}],
    details: {7: runningChat(7, 11), 8: runningChat(8, 81)},
  });
  await harness.ready();
  const gate = harness.hold("GET", "/api/assistant/chats/8");
  const selecting = harness.navigate("#assistant/8");
  await gate.started;
  await harness.navigate("#settings");
  gate.respond(200, runningChat(8, 81));
  await selecting;
  await harness.navigate(harness.assistantHref());
  const state = harness.state();
  assert.equal(state.id, 8);
  assert.equal(state.chatId, 8);
  assert.equal(state.activeTurn, 81);
  assert.equal(state.hash, "#assistant/8");
});

test("explicit New during a delayed old detail load is not undone by that response", async () => {
  const harness = createHarness({
    hash: "#assistant/7",
    chats: [{id: 8, title: "Conversation 8"}, {id: 7, title: "Conversation 7"}],
    details: {7: runningChat(7, 11), 8: runningChat(8, 81)},
  });
  await harness.ready();
  const gate = harness.hold("GET", "/api/assistant/chats/8");
  const older = harness.navigate("#assistant/8");
  await gate.started;
  await harness.clickAction("assistant-new");
  gate.respond(200, runningChat(8, 81));
  await older;
  await harness.navigate("#assistant");
  assert.equal(harness.state().selectedId, null, "New must clear the remembered selection");
  await harness.navigate("#settings");
  await harness.navigate(harness.assistantHref());
  const state = harness.state();
  assert.equal(state.chatId, null, "old detail response must not make New return to chat 8");
  assert.equal(state.id, null);
  assert.equal(state.hash, "#assistant");
});

test("a stale assistant failure cannot replace Settings or its current view", async () => {
  const harness = createHarness({
    hash: "#assistant/7",
    chats: [{id: 8, title: "Conversation 8"}, {id: 7, title: "Conversation 7"}],
    details: {7: runningChat(7, 11), 8: runningChat(8, 81)},
  });
  await harness.ready();
  const gate = harness.hold("GET", "/api/assistant/chats/8");
  const older = harness.navigate("#assistant/8");
  await gate.started;
  await harness.navigate("#settings");
  assert.match(harness.html(), /Workspace settings/);
  gate.respond(500, {detail: "Stale fixture failure"});
  await older;
  await harness.ready();
  const state = harness.state();
  assert.equal(state.route, "settings");
  assert.match(harness.html(), /Workspace settings/);
  assert.doesNotMatch(harness.html(), /Unable to open this view/);
});

test("submit pending while leaving: no forced return, no duplicate POST, accepted chat recoverable", async () => {
  const harness = createHarness({hash: "#assistant", chats: [], details: {}, nextChatId: 21, nextTurnId: 31});
  await harness.ready();
  harness.input("assistant-request", "Create the accepted fixture conversation");
  const createGate = harness.hold("POST", "/api/assistant/chats");
  const turnGate = harness.hold("POST", "/api/assistant/chats/21/turns");
  const submission = harness.submit();
  await createGate.started;
  await harness.navigate("#settings");
  harness.addChat(runningChat(21, 31, "Accepted conversation 21"));
  const created = fixtureChat(21, {title: "Accepted conversation 21"});
  createGate.respond(201, created);
  await turnGate.started;
  assert.equal(harness.posts(/^\/api\/assistant\/chats$/).length, 1, "exactly one create request");
  assert.equal(harness.posts(/\/turns$/).length, 1, "exactly one turn request");
  assert.equal(harness.location(), "#settings", "in-flight submit must not force navigation");
  turnGate.respond(202, {id: 31, chat_id: 21, status: "running"});
  await submission;
  await harness.ready();
  assert.equal(harness.state().route, "settings");
  assert.equal(harness.location(), "#settings");
  assert.equal(harness.state().selectedId, 21, "accepted chat must be remembered in memory");
  assert.equal(harness.posts(/^\/api\/assistant\/chats$/).length, 1);
  assert.equal(harness.posts(/\/turns$/).length, 1);
  const href = harness.assistantHref();
  await harness.navigate(href);
  const state = harness.state();
  assert.equal(state.id, 21);
  assert.equal(state.chatId, 21);
  assert.equal(state.activeTurn, 31);
  assert.equal(state.hash, "#assistant/21");
  assert.match(harness.html(), /Working locally/);
});

test("new turn failure while away leaves an honest error instead of resuming an empty chat", async () => {
  const harness = createHarness({hash: "#assistant", chats: [], details: {}, nextChatId: 23, nextTurnId: 34});
  await harness.ready();
  harness.input("assistant-request", "Create then fail the turn");
  const createGate = harness.hold("POST", "/api/assistant/chats");
  const turnGate = harness.hold("POST", "/api/assistant/chats/23/turns");
  const submission = harness.submit();
  await createGate.started;
  await harness.navigate("#settings");
  harness.addChat(fixtureChat(23, {title: "Created but failed 23"}));
  createGate.respond(201, fixtureChat(23, {title: "Created but failed 23"}));
  await turnGate.started;
  turnGate.respond(500, {detail: "The local worker rejected this turn"});
  await submission;
  await harness.ready();
  assert.equal(harness.state().route, "settings");
  assert.equal(harness.location(), "#settings");
  assert.equal(harness.state().selectedId, null);
  assert.equal(harness.state().error, "The local worker rejected this turn");
  await harness.navigate(harness.assistantHref());
  const state = harness.state();
  assert.equal(state.chatId, null);
  assert.equal(state.selectedId, null);
  assert.equal(state.draft, "Create then fail the turn");
  assert.match(harness.html(), /The local worker rejected this turn/);
  assert.ok(state.historyIds.includes(23), "the empty created chat remains in history");
});

test("old submit success cannot clear a new draft or jump back to the old chat", async () => {
  const harness = createHarness({
    hash: "#assistant/7",
    chats: [{id: 7, title: "Settled conversation 7"}],
    details: {7: completedChat(7, 11)},
    nextTurnId: 32,
  });
  await harness.ready();
  harness.input("assistant-request", "Old follow-up request");
  const turnGate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const submission = harness.submit();
  await turnGate.started;
  await harness.clickAction("assistant-new");
  await harness.navigate("#assistant");
  harness.input("assistant-request", "Fresh draft after New");
  turnGate.respond(202, {id: 32, chat_id: 7, status: "running"});
  await submission;
  await harness.ready();
  const state = harness.state();
  assert.equal(state.hash, "#assistant", "old success must not navigate to chat 7");
  assert.equal(state.route, "assistant");
  assert.equal(state.chatId, null, "old success must not restore the old conversation");
  assert.equal(state.draft, "Fresh draft after New", "old success must not clear the new draft");
  assert.equal(state.selectedId, null);
  assert.match(harness.html(), /Fresh draft after New/);
});

test("old submit failure cannot pollute the new conversation error area", async () => {
  const harness = createHarness({
    hash: "#assistant/7",
    chats: [{id: 7, title: "Settled conversation 7"}],
    details: {7: completedChat(7, 11)},
  });
  await harness.ready();
  harness.input("assistant-request", "Old failing follow-up");
  const turnGate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const submission = harness.submit();
  await turnGate.started;
  await harness.clickAction("assistant-new");
  await harness.navigate("#assistant");
  harness.input("assistant-request", "Fresh draft after failure");
  turnGate.respond(500, {detail: "Old follow-up failed in the background"});
  await submission;
  await harness.ready();
  const state = harness.state();
  assert.equal(state.hash, "#assistant");
  assert.equal(state.route, "assistant");
  assert.equal(state.chatId, null);
  assert.equal(state.error, "", "old failure must not become the new view's error");
  assert.equal(state.draft, "Fresh draft after failure");
  assert.doesNotMatch(harness.html(), /Old follow-up failed in the background/);
});

test("create pending then explicit New: accepted turn is not lost, new draft is not overwritten", async () => {
  const harness = createHarness({hash: "#assistant", chats: [], details: {}, nextChatId: 22, nextTurnId: 33});
  await harness.ready();
  harness.input("assistant-request", "First pending create");
  const createGate = harness.hold("POST", "/api/assistant/chats");
  const turnGate = harness.hold("POST", "/api/assistant/chats/22/turns");
  const submission = harness.submit();
  await createGate.started;
  await harness.clickAction("assistant-new");
  await harness.navigate("#assistant");
  harness.input("assistant-request", "Second draft while create is pending");
  harness.addChat(runningChat(22, 33, "Accepted conversation 22"));
  createGate.respond(201, fixtureChat(22, {title: "Accepted conversation 22"}));
  await turnGate.started;
  turnGate.respond(202, {id: 33, chat_id: 22, status: "running"});
  await submission;
  await harness.ready();
  const state = harness.state();
  assert.equal(state.route, "assistant");
  assert.equal(state.chatId, null);
  assert.equal(state.hash, "#assistant");
  assert.equal(state.draft, "Second draft while create is pending");
  assert.equal(state.selectedId, null);
  assert.ok(harness.state().historyIds.includes(22), "accepted chat must remain in conversation history");
  assert.equal(harness.posts(/^\/api\/assistant\/chats$/).length, 1);
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("logout clears only the in-memory assistant selection", async () => {
  const harness = createHarness({
    hash: "#assistant/7",
    chats: [{id: 7, title: "Conversation 7"}],
    details: {7: runningChat(7, 11)},
  });
  await harness.ready();
  assert.equal(harness.state().selectedId, 7);
  await harness.clickAction("logout");
  const state = harness.state();
  assert.equal(state.selectedId, null);
  assert.equal(state.chatId, null);
  assert.equal(state.draft, "");
});

test("assistant submit -> Overview -> late success keeps Overview", async () => {
  const harness = createHarness({
    hash: "#assistant/7", chats: [{id: 7, title: "Settled 7"}],
    details: {7: completedChat(7, 11)},
  });
  await harness.ready();
  harness.input("assistant-request", "Late response while Overview is selected");
  const gate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const submission = harness.submit();
  await gate.started;
  await harness.navigate("#dashboard");
  assert.equal(harness.state().route, "dashboard");
  gate.respond(202, {id: 31, chat_id: 7, status: "running"});
  await submission;
  await harness.ready();
  assert.equal(harness.location(), "#dashboard", "late success must not pull the user away from Overview");
  assert.equal(harness.state().route, "dashboard");
  assert.equal(harness.state().selectedId, 7, "accepted task should remain recoverable");
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("new submit from Overview -> Settings -> Overview stays where user returned", async () => {
  const harness = createHarness({hash: "#dashboard", chats: [], details: {}, nextChatId: 24});
  await harness.ready();
  harness.input("assistant-request", "Create from Overview, but keep later navigation");
  const createGate = harness.hold("POST", "/api/assistant/chats");
  const turnGate = harness.hold("POST", "/api/assistant/chats/24/turns");
  const submission = harness.submit();
  await createGate.started;
  await harness.navigate("#settings");
  await harness.navigate("#dashboard");
  harness.addChat(runningChat(24, 35));
  createGate.respond(201, fixtureChat(24));
  await turnGate.started;
  turnGate.respond(202, {id: 35, chat_id: 24, status: "running"});
  await submission;
  await harness.ready();
  assert.equal(harness.location(), "#dashboard", "returning to the same route is a new navigation intent");
  assert.equal(harness.state().route, "dashboard");
  assert.equal(harness.state().selectedId, 24);
  assert.equal(harness.posts(/^\/api\/assistant\/chats$/).length, 1);
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("pending retry -> Settings -> same chat before acceptance refreshes new active turn", async () => {
  const harness = createHarness({
    hash: "#assistant/7", chats: [{id: 7, title: "Failed 7"}],
    details: {7: failedChat(7, 11)},
  });
  await harness.ready();
  const gate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const retry = harness.clickAction("assistant-retry", {turn: "11"});
  await gate.started;
  await harness.navigate("#settings");
  await harness.navigate("#assistant/7");
  assert.equal(harness.state().activeTurn, null);
  harness.updateChat(runningChat(7, 36));
  gate.respond(202, {id: 36, chat_id: 7, status: "running"});
  await retry;
  await harness.ready();
  await harness.assistantPoll();
  assert.equal(harness.state().chatId, 7);
  assert.equal(harness.state().activeTurn, 36, "accepted retry must become visible after returning to its chat");
  assert.match(harness.html(), /Working locally/);
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("logout during pending create invalidates late create continuation", async () => {
  const harness = createHarness({hash: "#assistant", chats: [], details: {}});
  await harness.ready();
  harness.input("assistant-request", "Old request before signing out");
  const createGate = harness.hold("POST", "/api/assistant/chats");
  const turnGate = harness.hold("POST", "/api/assistant/chats/25/turns");
  const submission = harness.submit();
  await createGate.started;
  await harness.clickAction("logout");
  assert.deepEqual(Array.from(harness.state().historyIds), []);
  createGate.respond(201, fixtureChat(25, {title: "Old signed-out conversation"}));
  await harness.ready();
  harness.record("late create has returned after logout, before any new turn response");
  try {
    assert.deepEqual({historyIds: Array.from(harness.state().historyIds), turnPosts: harness.posts(/\/turns$/).length},
      {historyIds: [], turnPosts: 0}, "signed-out intent must not repopulate cleared history or issue a new turn POST");
  } finally {
    // If a buggy candidate did issue the POST, mimic an actual signed-out server.
    // No turn is accepted by this fixture, and no real request is sent.
    turnGate.respond(401, {detail: "Sign in required"});
    await submission;
    await harness.ready();
  }
});

test("submit from Overview while staying opens the accepted chat", async () => {
  const harness = createHarness({hash: "#dashboard", chats: [], details: {}, nextChatId: 40, nextTurnId: 50});
  await harness.ready();
  harness.input("assistant-request", "Create from Overview and stay there");
  const createGate = harness.hold("POST", "/api/assistant/chats");
  const turnGate = harness.hold("POST", "/api/assistant/chats/40/turns");
  const submission = harness.submit();
  await createGate.started;
  assert.equal(harness.location(), "#dashboard", "submitting must not navigate before acceptance");
  harness.addChat(runningChat(40, 50));
  createGate.respond(201, fixtureChat(40, {title: "Accepted 40"}));
  await turnGate.started;
  turnGate.respond(202, {id: 50, chat_id: 40, status: "running"});
  await submission;
  await harness.ready();
  assert.equal(harness.location(), "#assistant/40", "an in-place Overview submit may open the accepted chat");
  assert.equal(harness.state().selectedId, 40);
  assert.equal(harness.posts(/^\/api\/assistant\/chats$/).length, 1);
  assert.equal(harness.posts(/\/turns$/).length, 1);
  await harness.navigate(harness.location());
  const state = harness.state();
  assert.equal(state.route, "assistant");
  assert.equal(state.chatId, 40);
  assert.equal(state.activeTurn, 50);
  assert.match(harness.html(), /Working locally/);
});

test("in-place follow-up refreshes its own accepted turn without navigation", async () => {
  const harness = createHarness({
    hash: "#assistant/7", chats: [{id: 7, title: "Completed 7"}],
    details: {7: completedChat(7, 11)}, nextTurnId: 32,
  });
  await harness.ready();
  harness.input("assistant-request", "Follow up in the same conversation");
  const gate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const submission = harness.submit();
  await gate.started;
  harness.updateChat(runningChat(7, 32));
  gate.respond(202, {id: 32, chat_id: 7, status: "running"});
  await submission;
  await harness.ready();
  const state = harness.state();
  assert.equal(harness.location(), "#assistant/7");
  assert.equal(state.route, "assistant");
  assert.equal(state.chatId, 7);
  assert.equal(state.activeTurn, 32, "same-chat acceptance must refresh the current detail");
  assert.equal(state.selectedId, 7);
  assert.equal(state.draft, "");
  assert.equal(state.busy, false);
  assert.match(harness.html(), /Working locally/);
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("retry accepted while Settings stays put and does not pollute a later B", async () => {
  const harness = createHarness({
    hash: "#assistant/7", chats: [{id: 8, title: "Conversation 8"}, {id: 7, title: "Failed 7"}],
    details: {7: failedChat(7, 11), 8: runningChat(8, 81)},
  });
  await harness.ready();
  const gate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const retry = harness.clickAction("assistant-retry", {turn: "11"});
  await gate.started;
  await harness.navigate("#settings");
  const detailsBefore = harness.detailCalls(7);
  harness.updateChat(runningChat(7, 36));
  gate.respond(202, {id: 36, chat_id: 7, status: "running"});
  await retry;
  await harness.ready();
  assert.equal(harness.location(), "#settings");
  assert.equal(harness.state().route, "settings");
  assert.equal(harness.state().busy, false);
  assert.equal(harness.detailCalls(7), detailsBefore, "remaining on Settings must not fetch or apply chat 7");
  assert.equal(harness.posts(/\/turns$/).length, 1);
  await harness.navigate("#assistant/8");
  const state = harness.state();
  assert.equal(state.route, "assistant");
  assert.equal(state.chatId, 8);
  assert.equal(state.activeTurn, 81, "later B selection must keep B's running state");
  assert.equal(harness.location(), "#assistant/8");
  assert.match(harness.html(), /Working locally/);
});

test("retry accepted after New does not restore the old chat or selection", async () => {
  const harness = createHarness({
    hash: "#assistant/7", chats: [{id: 7, title: "Failed 7"}],
    details: {7: failedChat(7, 11)},
  });
  await harness.ready();
  const gate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const retry = harness.clickAction("assistant-retry", {turn: "11"});
  await gate.started;
  await harness.clickAction("assistant-new");
  await harness.navigate("#assistant");
  harness.updateChat(runningChat(7, 36));
  gate.respond(202, {id: 36, chat_id: 7, status: "running"});
  await retry;
  await harness.ready();
  const state = harness.state();
  assert.equal(harness.location(), "#assistant");
  assert.equal(state.chatId, null, "New must remain the current selection");
  assert.equal(state.selectedId, null);
  assert.equal(state.activeTurn, null);
  assert.doesNotMatch(harness.html(), /Working locally/);
  assert.equal(state.busy, false);
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("late follow-up accepted while on Overview remains recoverable on return", async () => {
  const harness = createHarness({
    hash: "#assistant/7", chats: [{id: 7, title: "Completed 7"}],
    details: {7: completedChat(7, 11)},
  });
  await harness.ready();
  harness.input("assistant-request", "Late follow-up while Overview is open");
  const gate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const submission = harness.submit();
  await gate.started;
  await harness.navigate("#dashboard");
  harness.updateChat(runningChat(7, 31));
  gate.respond(202, {id: 31, chat_id: 7, status: "running"});
  await submission;
  await harness.ready();
  assert.equal(harness.location(), "#dashboard");
  assert.equal(harness.state().route, "dashboard");
  assert.equal(harness.state().selectedId, 7, "accepted chat stays recoverable in memory");
  await harness.navigate("#assistant/7");
  const state = harness.state();
  assert.equal(state.chatId, 7);
  assert.equal(state.activeTurn, 31, "returning reads the accepted running turn");
  assert.match(harness.html(), /Working locally/);
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("late follow-up after opening B keeps B's selection and state", async () => {
  const harness = createHarness({
    hash: "#assistant/7", chats: [{id: 8, title: "Conversation 8"}, {id: 7, title: "Completed 7"}],
    details: {7: completedChat(7, 11), 8: runningChat(8, 81)},
  });
  await harness.ready();
  harness.input("assistant-request", "Old follow-up that returns after B is opened");
  const gate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const submission = harness.submit();
  await gate.started;
  await harness.navigate("#assistant/8");
  harness.updateChat(runningChat(7, 31));
  gate.respond(202, {id: 31, chat_id: 7, status: "running"});
  await submission;
  await harness.ready();
  const state = harness.state();
  assert.equal(harness.location(), "#assistant/8");
  assert.equal(state.chatId, 8, "late 7 success must not replace the open chat 8");
  assert.equal(state.activeTurn, 81);
  assert.equal(state.selectedId, 8, "late 7 success must not overwrite the explicit B selection");
  assert.doesNotMatch(harness.html(), /Reconcile synthetic input for 7/, "late 7 content must not replace chat 8");
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("retry accepted after selecting B leaves B's running state intact", async () => {
  const harness = createHarness({
    hash: "#assistant/7", chats: [{id: 8, title: "Conversation 8"}, {id: 7, title: "Failed 7"}],
    details: {7: failedChat(7, 11), 8: runningChat(8, 81)},
  });
  await harness.ready();
  const gate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const retry = harness.clickAction("assistant-retry", {turn: "11"});
  await gate.started;
  await harness.change("assistant-history", "8");
  await harness.navigate("#assistant/8");
  assert.equal(harness.state().chatId, 8);
  const detailsBefore = harness.detailCalls(7);
  harness.updateChat(runningChat(7, 36));
  gate.respond(202, {id: 36, chat_id: 7, status: "running"});
  await retry;
  await harness.ready();
  const state = harness.state();
  assert.equal(harness.location(), "#assistant/8");
  assert.equal(state.chatId, 8);
  assert.equal(state.activeTurn, 81, "B must keep its own running turn");
  assert.equal(state.selectedId, 8);
  assert.equal(harness.detailCalls(7), detailsBefore, "the old retry must not fetch chat 7 over B");
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("logout then re-login keeps a new submit busy when an old create returns", async () => {
  const harness = createHarness({hash: "#assistant", chats: [], details: {}, nextChatId: 25, nextTurnId: 35});
  await harness.ready();
  harness.input("assistant-request", "Old request before signing out");
  const oldCreate = harness.hold("POST", "/api/assistant/chats");
  const oldTurn = harness.hold("POST", "/api/assistant/chats/25/turns");
  const oldSubmission = harness.submit();
  await oldCreate.started;
  await harness.clickAction("logout");
  assert.deepEqual(Array.from(harness.state().historyIds), []);
  await harness.login("Second Owner");
  await harness.navigate("#assistant");
  harness.input("assistant-request", "Fresh request in the new session");
  const newCreate = harness.hold("POST", "/api/assistant/chats");
  const newTurn = harness.hold("POST", "/api/assistant/chats/26/turns");
  const newSubmission = harness.submit();
  await newCreate.started;
  assert.equal(harness.state().busy, true);
  harness.record("before old create returns into the new session");
  oldCreate.respond(201, fixtureChat(25, {title: "Old signed-out conversation"}));
  await harness.ready();
  try {
    const state = harness.state();
    assert.deepEqual(Array.from(state.historyIds), [], "old create must not repopulate signed-out history");
    assert.equal(harness.posts(/\/turns$/).length, 0, "old create must not continue with a turn POST");
    assert.equal(state.busy, true, "old finally must not release the new submit's busy state");
    assert.equal(state.draft, "Fresh request in the new session");
    assert.equal(state.error, "");
    assert.equal(state.route, "assistant");
  } finally {
    // Release a buggy candidate's unexpected continuation; no turn is accepted here.
    oldTurn.respond(401, {detail: "Sign in required"});
    await oldSubmission;
    await harness.ready();
  }
  harness.addChat(runningChat(26, 36));
  newCreate.respond(201, fixtureChat(26, {title: "New session conversation"}));
  await newTurn.started;
  newTurn.respond(202, {id: 36, chat_id: 26, status: "running"});
  await newSubmission;
  await harness.ready();
  const state = harness.state();
  assert.equal(state.sessionUsername, "Second Owner");
  assert.equal(state.selectedId, 26);
  assert.ok(state.historyIds.includes(26));
  assert.equal(harness.posts(/^\/api\/assistant\/chats$/).length, 2);
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("an old 401 after re-login does not clear the new session's busy state", async () => {
  const harness = createHarness({hash: "#assistant", chats: [], details: {}, nextChatId: 25, nextTurnId: 35});
  await harness.ready();
  harness.input("assistant-request", "Old request that will be rejected");
  const oldCreate = harness.hold("POST", "/api/assistant/chats");
  const oldTurn = harness.hold("POST", "/api/assistant/chats/25/turns");
  const oldSubmission = harness.submit();
  await oldCreate.started;
  await harness.clickAction("logout");
  await harness.login("Second Owner");
  await harness.navigate("#assistant");
  harness.input("assistant-request", "New request unaffected by the stale 401");
  const newCreate = harness.hold("POST", "/api/assistant/chats");
  const newTurn = harness.hold("POST", "/api/assistant/chats/26/turns");
  const newSubmission = harness.submit();
  await newCreate.started;
  harness.record("before stale create 401 arrives");
  oldCreate.respond(401, {detail: "Sign in required"});
  await harness.ready();
  try {
    const state = harness.state();
    assert.equal(state.sessionUsername, "Second Owner", "stale 401 must not sign out the new session");
    assert.equal(state.busy, true, "stale 401 must not clear the new submit's busy state");
    assert.equal(state.draft, "New request unaffected by the stale 401");
    assert.equal(state.error, "");
    assert.deepEqual(Array.from(state.historyIds), []);
    assert.equal(harness.posts(/\/turns$/).length, 0);
  } finally {
    oldTurn.respond(401, {detail: "Sign in required"});
    await oldSubmission;
    await harness.ready();
  }
  harness.addChat(runningChat(26, 36));
  newCreate.respond(201, fixtureChat(26, {title: "New session conversation"}));
  await newTurn.started;
  newTurn.respond(202, {id: 36, chat_id: 26, status: "running"});
  await newSubmission;
  await harness.ready();
  const state = harness.state();
  assert.equal(state.sessionUsername, "Second Owner");
  assert.equal(state.selectedId, 26);
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("an in-flight old navigate cannot restore the session after logout", async () => {
  const harness = createHarness({
    hash: "#assistant/7", chats: [{id: 7, title: "Conversation 7"}],
    details: {7: runningChat(7, 11)},
  });
  await harness.ready();
  const gate = harness.hold("GET", "/api/session");
  const navigation = harness.navigate("#assistant/8");
  await gate.started;
  await harness.clickAction("logout");
  assert.equal(harness.state().sessionUsername, null);
  gate.respond(200, {username: "Old Fixture Owner", setup_required: false});
  await navigation;
  await harness.ready();
  const state = harness.state();
  assert.equal(state.sessionUsername, null, "an old /session response must not sign the new context back in");
  assert.equal(state.selectedId, null);
  assert.equal(state.chatId, null);
  assert.deepEqual(Array.from(state.historyIds), []);
  assert.match(harness.html(), /Welcome back/);
});

test("a current 401 during pending create invalidates memory and continuation", async () => {
  const harness = createHarness({hash: "#assistant", chats: [], details: {}, nextChatId: 25});
  await harness.ready();
  harness.input("assistant-request", "Create that is rejected by the current session");
  const createGate = harness.hold("POST", "/api/assistant/chats");
  const turnGate = harness.hold("POST", "/api/assistant/chats/25/turns");
  const submission = harness.submit();
  await createGate.started;
  createGate.respond(401, {detail: "Sign in required"});
  await submission;
  await harness.ready();
  try {
    const state = harness.state();
    assert.deepEqual(Array.from(state.historyIds), []);
    assert.equal(harness.posts(/\/turns$/).length, 0, "401 must not start a continuation");
    assert.equal(state.busy, false);
    assert.equal(state.chatId, null);
    assert.equal(state.selectedId, null);
    assert.equal(state.draft, "");
    assert.equal(state.sessionUsername, null);
    assert.equal(state.sessionEpoch, 1);
    assert.match(harness.html(), /Welcome back/);
  } finally {
    turnGate.respond(401, {detail: "Sign in required"});
  }
});

test("accepted Retry with a current detail GET error reports that error", async () => {
  const harness = createHarness({hash: "#assistant/7", chats: [{id: 7, title: "Failed 7"}], details: {7: failedChat(7, 11)}});
  await harness.ready();
  const postGate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const detailGate = harness.hold("GET", "/api/assistant/chats/7");
  const retry = harness.clickAction("assistant-retry", {turn: "11"});
  await postGate.started;
  harness.updateChat(runningChat(7, 36));
  postGate.respond(202, {id: 36, chat_id: 7, status: "running"});
  await detailGate.started;
  detailGate.respond(500, {detail: "Synthetic current detail refresh failed"});
  await retry;
  await harness.ready();
  await harness.assistantPoll();
  harness.record("accepted Retry after its current detail refresh failed");
  const toast = vm.runInContext("document.getElementById('toast').textContent", harness.context);
  const visible = harness.html() + " " + toast;
  assert.match(visible, /Synthetic current detail refresh failed/, "current refresh error must be visible, not leave an unexplained old failed screen");
  assert.equal(harness.posts(/\/turns$/).length, 1);
  await harness.navigate("#assistant/7");
  assert.equal(harness.state().activeTurn, 36);
});

test("pending Retry -> select B -> select A again refreshes accepted turn", async () => {
  const harness = createHarness({hash: "#assistant/7", chats: [{id: 8, title: "B"}, {id: 7, title: "A"}], details: {7: failedChat(7, 11), 8: runningChat(8, 81)}});
  await harness.ready();
  const gate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const retry = harness.clickAction("assistant-retry", {turn: "11"});
  await gate.started;
  await harness.change("assistant-history", "8");
  await harness.navigate("#assistant/8");
  await harness.change("assistant-history", "7");
  await harness.navigate("#assistant/7");
  assert.equal(harness.state().activeTurn, null);
  harness.updateChat(runningChat(7, 36));
  gate.respond(202, {id: 36, chat_id: 7, status: "running"});
  await retry;
  await harness.ready();
  await harness.assistantPoll();
  assert.equal(harness.state().chatId, 7);
  assert.equal(harness.state().selectedId, 7);
  assert.equal(harness.state().activeTurn, 36, "current A must show its accepted turn even when the old draft selection epoch changed");
  assert.match(harness.html(), /Working locally/);
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("control: obsolete detail refresh error must not pollute B", async () => {
  const harness = createHarness({hash: "#assistant/7", chats: [{id: 8, title: "B"}, {id: 7, title: "A"}], details: {7: failedChat(7, 11), 8: runningChat(8, 81)}});
  await harness.ready();
  const postGate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const detailGate = harness.hold("GET", "/api/assistant/chats/7");
  const retry = harness.clickAction("assistant-retry", {turn: "11"});
  await postGate.started;
  postGate.respond(202, {id: 36, chat_id: 7, status: "running"});
  await detailGate.started;
  await harness.change("assistant-history", "8");
  await harness.navigate("#assistant/8");
  detailGate.respond(500, {detail: "Synthetic obsolete refresh error"});
  await retry;
  await harness.ready();
  assert.equal(harness.state().chatId, 8);
  assert.equal(harness.state().activeTurn, 81);
  assert.equal(harness.state().error, "");
  const toast = vm.runInContext("document.getElementById('toast').textContent", harness.context);
  assert.doesNotMatch(harness.html() + " " + toast, /Synthetic obsolete refresh error/);
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("Retry current detail error is visible and keeps the accepted turn recoverable", async () => {
  const harness = createHarness({hash: "#assistant/7", chats: [{id: 7, title: "Failed 7"}], details: {7: failedChat(7, 11)}});
  await harness.ready();
  const postGate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const detailGate = harness.hold("GET", "/api/assistant/chats/7");
  const retry = harness.clickAction("assistant-retry", {turn: "11"});
  await postGate.started;
  harness.updateChat(runningChat(7, 36));
  postGate.respond(202, {id: 36, chat_id: 7, status: "running"});
  await detailGate.started;
  detailGate.respond(500, {detail: "Synthetic current retry refresh failed"});
  await retry;
  await harness.ready();
  const toast = vm.runInContext("document.getElementById('toast').textContent", harness.context);
  assert.match(harness.html() + " " + toast, /Synthetic current retry refresh failed/);
  assert.equal(harness.state().activeTurn, 36, "the accepted turn identity must not be lost when detail refresh fails");
  assert.equal(harness.posts(/\/turns$/).length, 1);
  assert.equal(harness.posts(/^\/api\/assistant\/chats$/).length, 0);
  await harness.assistantPoll();
  assert.equal(harness.state().activeTurn, 36, "normal polling must be able to recover the accepted turn");
  assert.match(harness.html(), /Working locally/);
});

test("Submit current detail error is visible and keeps the accepted turn recoverable", async () => {
  const harness = createHarness({hash: "#assistant/7", chats: [{id: 7, title: "Completed 7"}], details: {7: completedChat(7, 11)}});
  await harness.ready();
  harness.input("assistant-request", "Submit with a failing current detail refresh");
  const postGate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const detailGate = harness.hold("GET", "/api/assistant/chats/7");
  const submission = harness.submit();
  await postGate.started;
  harness.updateChat(runningChat(7, 32));
  postGate.respond(202, {id: 32, chat_id: 7, status: "running"});
  await detailGate.started;
  detailGate.respond(500, {detail: "Synthetic current submit refresh failed"});
  await submission;
  await harness.ready();
  const toast = vm.runInContext("document.getElementById('toast').textContent", harness.context);
  assert.match(harness.html() + " " + toast, /Synthetic current submit refresh failed/);
  assert.equal(harness.state().activeTurn, 32, "the accepted turn identity must not be lost when detail refresh fails");
  assert.equal(harness.posts(/\/turns$/).length, 1);
  await harness.assistantPoll();
  assert.equal(harness.state().activeTurn, 32);
  assert.match(harness.html(), /Working locally/);
  assert.equal(harness.state().draft, "");
});

test("Submit A -> B -> A refreshes current A but keeps the later new draft", async () => {
  const harness = createHarness({
    hash: "#assistant/7", chats: [{id: 8, title: "B"}, {id: 7, title: "A"}],
    details: {7: completedChat(7, 11), 8: completedChat(8, 81)},
  });
  await harness.ready();
  harness.input("assistant-request", "Old submit that is still in flight");
  const gate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const submission = harness.submit();
  await gate.started;
  await harness.change("assistant-history", "8");
  await harness.navigate("#assistant/8");
  await harness.change("assistant-history", "7");
  await harness.navigate("#assistant/7");
  harness.input("assistant-request", "New draft typed after returning to A");
  assert.equal(harness.state().epoch, 2);
  harness.updateChat(runningChat(7, 31));
  gate.respond(202, {id: 31, chat_id: 7, status: "running"});
  await submission;
  await harness.ready();
  const state = harness.state();
  assert.equal(harness.location(), "#assistant/7");
  assert.equal(state.chatId, 7);
  assert.equal(state.selectedId, 7);
  assert.equal(state.activeTurn, 31, "current A must be refreshed with its accepted turn");
  assert.equal(state.draft, "New draft typed after returning to A", "old submit must not clear the later draft");
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("Retry A -> B -> A refreshes current A and leaves the later draft alone", async () => {
  const harness = createHarness({
    hash: "#assistant/7", chats: [{id: 8, title: "B"}, {id: 7, title: "A"}],
    details: {7: failedChat(7, 11), 8: runningChat(8, 81)},
  });
  await harness.ready();
  const gate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const retry = harness.clickAction("assistant-retry", {turn: "11"});
  await gate.started;
  await harness.change("assistant-history", "8");
  await harness.navigate("#assistant/8");
  await harness.change("assistant-history", "7");
  await harness.navigate("#assistant/7");
  harness.input("assistant-request", "Draft typed after returning to A");
  harness.updateChat(runningChat(7, 36));
  gate.respond(202, {id: 36, chat_id: 7, status: "running"});
  await retry;
  await harness.ready();
  const state = harness.state();
  assert.equal(state.chatId, 7);
  assert.equal(state.selectedId, 7);
  assert.equal(state.activeTurn, 36);
  assert.equal(state.draft, "Draft typed after returning to A");
  assert.match(harness.html(), /Working locally/);
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("stale refresh success after switching to B does not overwrite B", async () => {
  const harness = createHarness({
    hash: "#assistant/7", chats: [{id: 8, title: "B"}, {id: 7, title: "A"}],
    details: {7: failedChat(7, 11), 8: runningChat(8, 81)},
  });
  await harness.ready();
  const postGate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const detailGate = harness.hold("GET", "/api/assistant/chats/7");
  const retry = harness.clickAction("assistant-retry", {turn: "11"});
  await postGate.started;
  postGate.respond(202, {id: 36, chat_id: 7, status: "running"});
  await detailGate.started;
  await harness.change("assistant-history", "8");
  await harness.navigate("#assistant/8");
  harness.updateChat(runningChat(7, 36));
  detailGate.respond(200, runningChat(7, 36));
  await retry;
  await harness.ready();
  const state = harness.state();
  assert.equal(harness.location(), "#assistant/8");
  assert.equal(state.chatId, 8);
  assert.equal(state.selectedId, 8);
  assert.equal(state.activeTurn, 81);
  assert.equal(state.error, "");
  assert.doesNotMatch(harness.html(), /Reconcile synthetic input for 7/);
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("stale refresh error after New does not pollute the new draft", async () => {
  const harness = createHarness({hash: "#assistant/7", chats: [{id: 7, title: "Failed 7"}], details: {7: failedChat(7, 11)}});
  await harness.ready();
  const postGate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const detailGate = harness.hold("GET", "/api/assistant/chats/7");
  const retry = harness.clickAction("assistant-retry", {turn: "11"});
  await postGate.started;
  postGate.respond(202, {id: 36, chat_id: 7, status: "running"});
  await detailGate.started;
  await harness.clickAction("assistant-new");
  await harness.navigate("#assistant");
  harness.input("assistant-request", "Fresh draft after New");
  detailGate.respond(500, {detail: "Synthetic stale refresh error"});
  await retry;
  await harness.ready();
  const toast = vm.runInContext("document.getElementById('toast').textContent", harness.context);
  assert.equal(harness.state().chatId, null);
  assert.equal(harness.state().selectedId, null);
  assert.equal(harness.state().draft, "Fresh draft after New");
  assert.equal(harness.state().error, "");
  assert.doesNotMatch(harness.html() + " " + toast, /Synthetic stale refresh error/);
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("stale refresh success after logout does not restore assistant state", async () => {
  const harness = createHarness({
    hash: "#assistant/7", chats: [{id: 7, title: "Failed 7"}], details: {7: failedChat(7, 11)},
  });
  await harness.ready();
  const postGate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const detailGate = harness.hold("GET", "/api/assistant/chats/7");
  const retry = harness.clickAction("assistant-retry", {turn: "11"});
  await postGate.started;
  postGate.respond(202, {id: 36, chat_id: 7, status: "running"});
  await detailGate.started;
  await harness.clickAction("logout");
  harness.updateChat(runningChat(7, 36));
  detailGate.respond(200, runningChat(7, 36));
  await retry;
  await harness.ready();
  const state = harness.state();
  assert.equal(state.sessionUsername, null);
  assert.equal(state.chatId, null);
  assert.equal(state.selectedId, null);
  assert.deepEqual(Array.from(state.historyIds), []);
  assert.match(harness.html(), /Welcome back/);
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("older navigation detail cannot roll back the newer accepted Retry detail", async () => {
  const harness = createHarness({hash: "#assistant/7", chats: [{id: 7, title: "A"}], details: {7: failedChat(7, 11)}});
  await harness.ready();
  const postGate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const retry = harness.clickAction("assistant-retry", {turn: "11"});
  await postGate.started;
  await harness.navigate("#settings");
  const olderDetail = harness.hold("GET", "/api/assistant/chats/7");
  const returning = harness.navigate("#assistant/7");
  await olderDetail.started;
  try {
    // The older read represents a failed snapshot obtained before acceptance,
    // whose response is delayed. The new read is the post-acceptance snapshot.
    harness.updateChat(runningChat(7, 36));
    postGate.respond(202, {id: 36, chat_id: 7, status: "running"});
    await retry;
    await harness.ready();
    harness.record("new helper detail applied while older navigation GET is pending");
    assert.equal(harness.state().activeTurn, 36, "new accepted Retry must first become visible");
  } finally {
    olderDetail.respond(200, failedChat(7, 11));
    await returning;
    await harness.ready();
  }
  harness.record("older navigation snapshot settled after newer helper snapshot");
  await harness.assistantPoll();
  assert.equal(harness.state().chatId, 7);
  assert.equal(harness.state().activeTurn, 36, "older same-chat navigation response must not roll back the newer running snapshot");
  assert.match(harness.html(), /Working locally/);
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("older navigation success cannot roll back a newer accepted Retry detail", async () => {
  const harness = createHarness({hash: "#assistant/7", chats: [{id: 7, title: "A"}], details: {7: failedChat(7, 11)}});
  await harness.ready();
  const postGate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const retry = harness.clickAction("assistant-retry", {turn: "11"});
  await postGate.started;
  await harness.navigate("#settings");
  const olderDetail = harness.hold("GET", "/api/assistant/chats/7");
  const returning = harness.navigate("#assistant/7");
  await olderDetail.started;
  harness.updateChat(runningChat(7, 36));
  postGate.respond(202, {id: 36, chat_id: 7, status: "running"});
  await retry;
  await harness.ready();
  assert.equal(harness.state().activeTurn, 36);
  olderDetail.respond(200, failedChat(7, 11));
  await returning;
  await harness.ready();
  await harness.assistantPoll();
  assert.equal(harness.state().activeTurn, 36, "older navigation detail must not roll back the newer accepted turn");
  assert.match(harness.html(), /Working locally/);
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("older navigation error cannot replace the newer applied detail", async () => {
  const harness = createHarness({hash: "#assistant/7", chats: [{id: 7, title: "A"}], details: {7: failedChat(7, 11)}});
  await harness.ready();
  const postGate = harness.hold("POST", "/api/assistant/chats/7/turns");
  const retry = harness.clickAction("assistant-retry", {turn: "11"});
  await postGate.started;
  await harness.navigate("#settings");
  const olderDetail = harness.hold("GET", "/api/assistant/chats/7");
  const returning = harness.navigate("#assistant/7");
  await olderDetail.started;
  harness.updateChat(runningChat(7, 36));
  postGate.respond(202, {id: 36, chat_id: 7, status: "running"});
  await retry;
  await harness.ready();
  olderDetail.respond(500, {detail: "Synthetic older navigation detail failure"});
  await returning;
  await harness.ready();
  assert.equal(harness.state().route, "assistant");
  assert.equal(harness.state().chatId, 7);
  assert.equal(harness.state().activeTurn, 36);
  assert.doesNotMatch(harness.html(), /Unable to open this view/);
  const toast = vm.runInContext("document.getElementById('toast').textContent", harness.context);
  assert.doesNotMatch(harness.html() + " " + toast, /Synthetic older navigation detail failure/);
  assert.equal(harness.posts(/\/turns$/).length, 1);
});

test("a newer completed read is not revived by an older running response", async () => {
  const harness = createHarness({hash: "#assistant/7", chats: [{id: 7, title: "A"}], details: {7: runningChat(7, 11)}});
  await harness.ready();
  await harness.navigate("#settings");
  const olderDetail = harness.hold("GET", "/api/assistant/chats/7");
  const returning = harness.navigate("#assistant/7");
  await olderDetail.started;
  harness.updateChat(completedChat(7, 11));
  await harness.assistantPoll();
  assert.equal(harness.state().activeTurn, null, "the newer poll must apply the completed state");
  olderDetail.respond(200, runningChat(7, 11));
  await returning;
  await harness.ready();
  assert.equal(harness.state().activeTurn, null, "older running detail must not revive an active turn after completion");
  assert.doesNotMatch(harness.html(), /Working locally/);
  assert.equal(harness.posts(/\/turns$/).length, 0);
});

test("an older poll response cannot overwrite a newer returned navigation detail", async () => {
  const harness = createHarness({hash: "#assistant/7", chats: [{id: 7, title: "A"}], details: {7: runningChat(7, 11)}});
  await harness.ready();
  const pollGate = harness.hold("GET", "/api/assistant/chats/7");
  const polling = harness.assistantPoll();
  await pollGate.started;
  await harness.navigate("#settings");
  harness.updateChat(completedChat(7, 11));
  await harness.navigate("#assistant/7");
  assert.equal(harness.state().activeTurn, null, "returning navigation must apply the completed detail");
  pollGate.respond(200, runningChat(7, 11));
  await polling;
  await harness.ready();
  assert.equal(harness.state().chatId, 7);
  assert.equal(harness.state().activeTurn, null, "older polling detail must not overwrite the newer navigation detail");
  assert.doesNotMatch(harness.html(), /Working locally/);
  assert.equal(harness.posts(/\/turns$/).length, 0);
});

test("an older poll error is silent after a newer navigation detail is applied", async () => {
  const harness = createHarness({hash: "#assistant/7", chats: [{id: 7, title: "A"}], details: {7: runningChat(7, 11)}});
  await harness.ready();
  const pollGate = harness.hold("GET", "/api/assistant/chats/7");
  const polling = harness.assistantPoll();
  await pollGate.started;
  await harness.navigate("#settings");
  harness.updateChat(completedChat(7, 11));
  await harness.navigate("#assistant/7");
  assert.equal(harness.state().activeTurn, null);
  pollGate.respond(500, {detail: "Synthetic older poll failure"});
  await polling;
  await harness.ready();
  const toast = vm.runInContext("document.getElementById('toast').textContent", harness.context);
  assert.equal(harness.state().activeTurn, null);
  assert.doesNotMatch(harness.html() + " " + toast, /Synthetic older poll failure/);
  assert.equal(harness.posts(/\/turns$/).length, 0);
});

test("old A polling during pending B load must not invalidate B navigation", async () => {
  const harness = createHarness({hash: "#assistant/7", chats: [{id: 8, title: "B"}, {id: 7, title: "A"}], details: {7: runningChat(7, 11), 8: runningChat(8, 81)}});
  await harness.ready();
  assert.equal(harness.state().chatId, 7);
  const gate = harness.hold("GET", "/api/assistant/chats/8");
  await harness.change("assistant-history", "8");
  const navigation = harness.navigate("#assistant/8");
  await gate.started;
  try {
    assert.equal(harness.state().id, 8);
    assert.equal(harness.state().selectedId, 8);
    assert.equal(harness.state().chatId, 7, "old detail can remain loaded while B is pending");
    await harness.assistantPoll();
    harness.record("interval fired while B is selected but its navigation detail is pending");
  } finally {
    gate.respond(200, runningChat(8, 81));
    await navigation;
    await harness.ready();
  }
  harness.record("B response settled after old A polling opportunity");
  assert.equal(harness.state().chatId, 8, "B's valid detail must apply; an out-of-view A poll must not make it obsolete");
  assert.equal(harness.state().id, 8);
  assert.equal(harness.state().selectedId, 8);
  assert.equal(harness.state().activeTurn, 81);
  const callsBefore = harness.detailCalls(8);
  await harness.assistantPoll();
  assert.equal(harness.detailCalls(8), callsBefore + 1, "future polling must target B");
  assert.equal(harness.posts(/\/turns$/).length, 0);
});

test("old A poll is not admitted while B is selected and B's detail is pending", async () => {
  const harness = createHarness({
    hash: "#assistant/7", chats: [{id: 8, title: "B"}, {id: 7, title: "A"}],
    details: {7: runningChat(7, 11), 8: runningChat(8, 81)},
  });
  await harness.ready();
  const gate = harness.hold("GET", "/api/assistant/chats/8");
  await harness.change("assistant-history", "8");
  const navigation = harness.navigate("#assistant/8");
  await gate.started;
  assert.equal(harness.state().id, 8);
  assert.equal(harness.state().chatId, 7);
  const aReadsBefore = harness.detailCalls(7);
  await harness.assistantPoll();
  assert.equal(harness.detailCalls(7), aReadsBefore, "an out-of-view A poll must not issue a detail GET");
  assert.equal(harness.detailCalls(8), 1, "B's pending navigation read must remain the only B read");
  gate.respond(200, runningChat(8, 81));
  await navigation;
  await harness.ready();
  assert.equal(harness.state().chatId, 8);
  assert.equal(harness.state().activeTurn, 81);
  const bReadsBefore = harness.detailCalls(8);
  await harness.assistantPoll();
  assert.equal(harness.detailCalls(8), bReadsBefore + 1, "after B applies, polling must target B");
  assert.equal(harness.posts(/\/turns$/).length, 0);
});

test("a current eligible poll still updates and remains ordered against older detail", async () => {
  const harness = createHarness({hash: "#assistant/7", chats: [{id: 7, title: "A"}], details: {7: runningChat(7, 11)}});
  await harness.ready();
  await harness.navigate("#settings");
  const olderDetail = harness.hold("GET", "/api/assistant/chats/7");
  const returning = harness.navigate("#assistant/7");
  await olderDetail.started;
  harness.updateChat(completedChat(7, 11));
  await harness.assistantPoll();
  assert.equal(harness.state().activeTurn, null, "the eligible current poll must apply the completed detail");
  olderDetail.respond(200, runningChat(7, 11));
  await returning;
  await harness.ready();
  assert.equal(harness.state().activeTurn, null, "the older navigation read must not revive active_turn");
  assert.doesNotMatch(harness.html(), /Working locally/);
  assert.equal(harness.posts(/\/turns$/).length, 0);
});

const EXPECTED_TESTS = 51;
const TEST_TIMEOUT_MS = 10000;
async function runWithTimeout(run) {
  let timer;
  try {
    return await Promise.race([
      Promise.resolve().then(run),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`Scenario timed out after ${TEST_TIMEOUT_MS} ms`)), TEST_TIMEOUT_MS);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}
async function main() {
  assert.equal(tests.length, EXPECTED_TESTS, "All navigation scenarios must be registered");
  for (const name of ["assistant.js", "app.js"]) {
    if (!fs.existsSync(path.join(source, name))) throw new Error(`Missing frontend file: ${name}`);
  }
  const results = [];
  for (const item of tests) {
    const firstHarness = testHarnesses.length;
    activeTestName = item.name;
    try {
      await runWithTimeout(item.run);
      results.push({name: item.name, status: "passed", evidence: testHarnesses.slice(firstHarness).map(entry => entry.api.evidence())});
      console.log(`PASS ${item.name}`);
    } catch (error) {
      results.push({name: item.name, status: "failed", error: error.message,
        evidence: testHarnesses.slice(firstHarness).map(entry => entry.api.evidence())});
      console.log(`FAIL ${item.name}: ${error.message}`);
    } finally {
      activeTestName = "";
    }
  }
  assert.equal(results.length, EXPECTED_TESTS, "All registered scenarios must execute");
  const passed = results.filter(item => item.status === "passed").length;
  const summary = {source, method: "Frontend JS in Node VM with synthetic DOM/API fixtures",
    real_browser_opened: false, user_data_read: false, model_called: false,
    total: results.length, passed, failed: results.length - passed, results};
  if (outFile) fs.writeFileSync(outFile, JSON.stringify(summary, null, 2) + "\n");
  console.log(JSON.stringify({total: summary.total, passed, failed: summary.failed}));
  if (summary.failed) process.exitCode = 1;
}
main().catch(error => { console.error(error); process.exitCode = 2; });
