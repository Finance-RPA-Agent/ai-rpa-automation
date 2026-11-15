"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const source = path.join(__dirname, "../product/static");
const original = fs.readFileSync(path.join(__dirname, "assistant-navigation.cjs"), "utf8");
const first = original.indexOf('test("running -> Settings');
assert.ok(first > 0);
const fixture = vm.runInNewContext(original.slice(0, first) + "\ncreateHarness", {
  require, console, URL, __dirname,
  process: {argv: ["node", "fixture", "--source", source]}, setImmediate, setTimeout, clearTimeout,
});

test("the report-folder button opens reports without submitting data work", async () => {
  const h = fixture({hash: "#assistant"}); await h.ready();
  assert.match(h.html(), /Open reports folder/);
  const gate = h.hold("POST", "/api/reports/open");
  const done = h.clickAction("reports-open"); await gate.started;
  gate.respond(200, {opened: true, path: "/workspace/exports/Reports"}); await done;
  assert.equal(h.posts(/./).length, 1);
  assert.equal(h.posts(/\/turns$/).length, 0);
});

test("Show report uses the saved report and folder without a download dialog", async () => {
  const h = fixture({hash: "#assistant"}); await h.ready();
  const saved = h.hold("POST", "/api/assistant/artifacts/example/export");
  const opened = h.hold("POST", "/api/reports/open");
  const done = h.clickAction("assistant-export", {artifact: "example"}); await saved.started;
  saved.respond(200, {handled: true, saved: true, path: "/workspace/exports/Reports/Assistant-example.xlsx"});
  await opened.started;
  opened.respond(200, {opened: true, path: "/workspace/exports/Reports"}); await done;
  assert.equal(h.posts(/./).length, 2);
  assert.equal(h.posts(/\/turns$/).length, 0);
});
