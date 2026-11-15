"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = path.join(__dirname, "../product/static");
const original = fs.readFileSync(path.join(__dirname, "assistant-navigation.cjs"), "utf8");
const first = original.indexOf('test("running -> Settings');
assert.ok(first > 0);
const fixture = vm.runInNewContext(original.slice(0, first) + "\ncreateHarness", {
  require, console, URL, __dirname,
  process: {argv: ["node", "fixture", "--source", source]}, setImmediate, setTimeout, clearTimeout,
});
async function harness(session) { const h = fixture({}); await h.ready(); Object.assign(h.fixture.session, session); await h.navigate("#dashboard"); return h; }
const demoSession = {username: "Demo User", setup_required: false, demo_mode: true};

test("demo entry submits no credentials and enters an identified demo workspace", async () => {
  const h = await harness({...demoSession, username: null});
  await h.ready();
  assert.match(h.html(), /Enter demo/);
  assert.match(h.html(), /value="Demo User" readonly/);
  assert.doesNotMatch(h.html(), /Create your workspace/);
  assert.equal(h.posts(/./).length, 0);
  const gate = h.hold("POST", "/api/demo-login");
  const pending = h.login("Ignored demo display name");
  await gate.started;
  assert.equal(Object.keys(h.posts(/demo-login/)[0].body || {}).length, 0);
  h.fixture.session = {...demoSession};
  gate.respond(200, demoSession); await pending;
  assert.match(h.html(), /Demo workspace/);
  assert.equal(h.state().sessionUsername, "Demo User");
  await h.navigate("#settings");
  assert.doesNotMatch(h.html(), /Change password/);
  await h.clickAction("logout");
  assert.match(h.html(), /Enter demo/);
  assert.doesNotMatch(h.html(), /Welcome back/);
});

test("an expired demo session returns to the demo entry", async () => {
  const h = await harness({...demoSession});
  await h.ready();
  const gate = h.hold("GET", "/api/model");
  const pending = h.navigate("#settings"); await gate.started;
  gate.respond(401, {detail: "Expired"}); await pending;
  assert.match(h.html(), /Enter demo/);
});

test("ordinary workspaces retain real username and password login", async () => {
  const h = await harness({username: null, setup_required: false, demo_mode: false});
  await h.ready();
  assert.match(h.html(), /Welcome back/);
  assert.doesNotMatch(h.html(), /Enter demo/);
  await h.login("Ordinary Owner");
  assert.equal(h.posts(/^\/api\/login$/).length, 1);
  assert.equal(h.posts(/demo-login/).length, 0);
});
