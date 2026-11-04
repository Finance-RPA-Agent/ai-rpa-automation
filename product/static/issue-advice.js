/* R3B: read-only, on-demand advice. No task mutations, persistence or model warmup. */
(function (root) {
  "use strict";
  const fallback = new Set(["model_timeout", "model_unavailable", "model_busy", "model_rejected", "model_error", "unsupported", "insufficient_evidence"]);
  const factSources = {
    F_FINDING: "rule", F_AMOUNT_SOURCE: "input", F_AMOUNT_BI: "reference",
    F_AMOUNT_DIFF: "rule", F_STATUS_SOURCE: "input", F_STATUS_BI: "reference",
  };
  const suggestions = new Set(["REVIEW_BOTH_SOURCES", "KEEP_PENDING_REVIEW", "VERIFY_REFERENCE_VALUE", "ENTER_VERIFIED_VALUE", "FIX_SOURCE_AND_REIMPORT"]);
  const fields = ["task_id", "issue_id", "revision", "evidence_digest", "mode", "status", "status_message", "model", "advisory_only", "facts", "explanation", "selected_fact_ids", "uncertainty", "suggestions"];
  const escape = (value) => String(value).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const text = (value, max = 4000) => typeof value === "string" && value.length > 0 && value.length <= max;
  const shape = (value, keys) => value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === keys.length && keys.every(k => Object.hasOwn(value, k));
  function validate(data, identity) {
    const fail = () => { throw new Error("Advice could not be verified. Refresh the task before requesting it again."); };
    if (!shape(data, fields) || data.task_id !== identity.taskId || data.issue_id !== identity.issueId ||
        data.revision !== identity.revision || data.evidence_digest !== identity.digest || data.advisory_only !== true ||
        data.uncertainty !== "ROOT_CAUSE_UNKNOWN" || !text(data.status_message) || !text(data.explanation)) fail();
    if (!(data.mode === "local_model" && data.status === "advice_ready" && data.model === "qwen3.5:4b") &&
        !(data.mode === "rules_only" && fallback.has(data.status) && data.model === null)) fail();
    if (!Array.isArray(data.facts) || !data.facts.length || data.facts.length > 6 ||
        !Array.isArray(data.suggestions) || !data.suggestions.length || data.suggestions.length > 5 ||
        !Array.isArray(data.selected_fact_ids) || !data.selected_fact_ids.length) fail();
    const ids = new Set();
    for (const fact of data.facts) {
      if (!shape(fact, ["id", "source", "label", "value"]) || !Object.hasOwn(factSources, fact.id) ||
          fact.source !== factSources[fact.id] || ids.has(fact.id) || !text(fact.label, 200) || !text(fact.value, 500)) fail();
      ids.add(fact.id);
    }
    if (!ids.has("F_FINDING") || new Set(data.selected_fact_ids).size !== data.selected_fact_ids.length ||
        data.selected_fact_ids.some(id => !ids.has(id))) fail();
    const choices = new Set();
    for (const choice of data.suggestions) {
      if (!shape(choice, ["id", "text", "requires_human_decision"]) || !suggestions.has(choice.id) ||
          choices.has(choice.id) || choice.requires_human_decision !== true || !text(choice.text)) fail();
      choices.add(choice.id);
    }
    return data;
  }
  function context(value) {
    const task = value?.task;
    if (!value?.session?.username || value.route !== "task" || value.view !== "review" || !task ||
        task.id !== value.taskId || task.status !== "waiting_confirmation" ||
        !Number.isSafeInteger(task.id) || task.id < 1 || !Number.isSafeInteger(task.revision) || task.revision < 1 ||
        !/^[a-f0-9]{64}$/.test(task.evidence_digest || "") || !Array.isArray(task.issues)) return null;
    return { session: value.session, username: value.session.username, sessionEpoch: value.sessionEpoch, token: value.token, hash: value.hash,
      task, taskId: task.id, revision: task.revision, digest: task.evidence_digest };
  }
  function same(a, b) {
    return Boolean(a && b && ["session", "username", "sessionEpoch", "token", "hash", "task", "taskId", "revision", "digest"].every(key => a[key] === b[key]));
  }
  function create({ getContext, request, refreshTask, changed = () => {}, schedule = setTimeout, unschedule = clearTimeout, timeoutMs = 60000 }) {
    let active = null, generation = 0;
    const states = new Map();
    // A local re-render or selection change cannot unlock a timed-out task snapshot.
    // The app replaces the snapshot on a successful task-detail read.
    const needsRefresh = new WeakMap();
    function requireRefresh(ctx, id) {
      if (!needsRefresh.has(ctx.task)) needsRefresh.set(ctx.task, new Set());
      needsRefresh.get(ctx.task).add(id);
    }
    function clearTimers(state) {
      unschedule(state.timer);
      unschedule(state.slowTimer);
      state.timer = state.slowTimer = undefined;
    }
    function evidenceOnly(data) {
      return data?.status === "unsupported" || data?.status === "insufficient_evidence";
    }
    function invalidate() {
      generation += 1;
      for (const state of states.values()) { clearTimers(state); state.abort?.abort(); }
      states.clear(); active = null;
      changed();
    }
    function sync() {
      const next = context(getContext());
      if (!same(active, next)) {
        if (active || states.size) invalidate();
        active = next;
      }
      return active;
    }
    function issueExists(ctx, id) {
      return text(id, 256) && ctx.task.issues.filter(i => i.id === id).length === 1;
    }
    function current(ctx, id, version, state) {
      return version === generation && same(ctx, context(getContext())) && issueExists(ctx, id) && states.get(id) === state;
    }
    async function explain(issueId) {
      const ctx = sync();
      const last = states.get(issueId);
      if (!ctx || !issueExists(ctx, issueId) || needsRefresh.get(ctx.task)?.has(issueId) ||
          last?.kind === "pending" || evidenceOnly(last?.data)) return;
      const version = generation, state = { kind: "pending", abort: new AbortController(),
        data: last?.data?.mode === "rules_only" ? last.data : null };
      states.set(issueId, state);
      const isCurrent = () => current(ctx, issueId, version, state);
      state.timer = schedule(() => {
        if (!isCurrent() || state.kind !== "pending") return;
        clearTimers(state);
        requireRefresh(ctx, issueId);
        state.kind = "error";
        state.message = "This advice request timed out in the page. The local model may still be running. Refresh the task before requesting again.";
        state.abort.abort(); changed();
      }, timeoutMs);
      state.slowTimer = schedule(() => {
        if (!isCurrent() || state.kind !== "pending") return;
        state.slow = true;
        changed();
      }, 10000);
      changed();
      try {
        const response = await request(`/tasks/${ctx.taskId}/issues/${encodeURIComponent(issueId)}/explanation`,
          { revision: ctx.revision, evidence_digest: ctx.digest },
          { signal: state.abort.signal, isCurrent: () => isCurrent() && state.kind === "pending" });
        if (!isCurrent() || state.kind !== "pending") return;
        state.data = validate(response, { ...ctx, issueId });
        state.kind = "ready";
      } catch (error) {
        if (!isCurrent() || state.kind !== "pending") return;
        state.kind = "error";
        if ([401, 403, 404, 409].includes(error.status)) {
          state.data = null;
          requireRefresh(ctx, issueId);
        }
        state.message = ({
          401: "Your session expired. Sign in again; previous advice has been discarded.",
          403: "You are not permitted to request this advice. No correction was made.",
          404: "This task or finding is no longer available. Refresh the current task.",
          409: "The task evidence has changed. Refresh the task; old advice has been discarded.",
        })[error.status] || (error.message?.startsWith("Advice could not be verified") ? error.message :
          "Advice could not be retrieved from the local service. No correction was made. You may refresh and try again.");
        if (error.status === 401) {
          invalidate();
          sync();
          states.set(issueId, state);
          changed();
        }
      } finally {
        clearTimers(state);
        if (isCurrent()) changed();
      }
    }
    async function refresh(issueId) {
      const ctx = sync();
      if (!ctx || !issueExists(ctx, issueId) || !needsRefresh.get(ctx.task)?.has(issueId) ||
          !refreshTask || states.get(issueId)?.kind === "refreshing") return;
      const version = generation, state = { kind: "refreshing", data: states.get(issueId)?.data,
        abort: new AbortController() };
      const isCurrent = () => current(ctx, issueId, version, state);
      states.set(issueId, state);
      changed();
      try {
        await refreshTask(ctx.taskId, { signal: state.abort.signal, isCurrent });
      } catch (error) {
        if (!isCurrent()) return;
        state.kind = "error";
        if ([403, 404, 409].includes(error.status)) state.data = null;
        state.message = ({
          403: "Permission to refresh this task was denied.",
          404: "This task is no longer available. Return to the task list.",
          409: "The task evidence has changed. Refresh the current task.",
        })[error.status] || "The task could not be refreshed. Try Refresh task again.";
        changed();
      }
    }
    function render(issueId) {
      const ctx = sync();
      if (!ctx || !issueExists(ctx, issueId)) return "";
      const state = states.get(issueId), pending = state?.kind === "pending";
      const locked = needsRefresh.get(ctx.task)?.has(issueId);
      const refreshing = state?.kind === "refreshing";
      const verify = evidenceOnly(state?.data);
      let body = '<p class="detail-text">Request advice for this finding only. Nothing is sent until you choose Explain / suggest.</p>';
      if (pending) body = state.slow
        ? '<p role="status">Still waiting for local advice. You can continue manual review or leave this page.</p>'
        : '<p role="status">Requesting local advice… First use can take longer. You can leave this page; no approval is implied.</p>';
      if (locked && !state) body = '<p>Refresh the task before requesting advice again.</p>';
      if (refreshing) body = '<p role="status">Refreshing task evidence…</p>';
      if (state?.kind === "error") body = `<p class="error-text" role="alert">${escape(state.message)}</p>`;
      if (state?.data) {
        body = state.kind === "ready" ? "" : body + '<p>Previous rule result for this finding.</p>';
        const d = state.data, local = d.mode === "local_model";
        body += `<h4 class="advice-provenance ${local ? "advice-local" : "advice-rules"}">${local ? "Local AI · validated evidence selection" : "Rule-based only · deterministic fallback"}</h4>
          <p>${escape(d.status_message)} <span class="mono">(${escape(d.status)})</span></p>
          <dl class="advice-facts">${d.facts.map(f => `<div><dt>${escape(f.label)} <span class="muted">${escape({ input: "Source input", reference: "Imported BI reference", rule: "Deterministic rule" }[f.source])}</span></dt><dd>${escape(f.value)}</dd></div>`).join("")}</dl>
          <p>${escape(d.explanation)}</p><h4>Suggested checks — independently verify first</h4>
          <ul>${d.suggestions.map(s => `<li>${escape(s.text)} <strong>Human decision required.</strong></li>`).join("")}</ul>
          <p class="detail-text">Revision ${escape(d.revision)} · Finding ${escape(d.issue_id)} · Evidence <code class="advice-digest">${escape(d.evidence_digest)}</code></p>`;
      }
      let label = "Explain / suggest";
      if (pending) label = "Requesting advice…";
      else if (verify) label = "Verify source evidence";
      else if (state) label = "Request advice again";
      if (verify) body += '<p>Verify the source records and reimport a corrected version if needed.</p>';
      return `<section class="issue-advice" aria-label="Advice for this finding"><button type="button" class="btn secondary" data-action="issue-advice" data-issue-id="${escape(issueId)}" ${pending || locked || verify ? "disabled" : ""}>${label}</button>
        ${locked && refreshTask ? `<button type="button" class="btn secondary" data-action="refresh-advice-task" data-issue-id="${escape(issueId)}" ${refreshing ? "disabled" : ""}>Refresh task</button>` : ""}
        <div class="advice-result" aria-live="polite" aria-atomic="true" aria-busy="${pending}">${body}</div>
        <p class="advice-boundary">Advice only. The cause is not established. No values are changed or approved. Use the separate Review correction controls after independent verification.</p></section>`;
    }
    return { explain, refresh, render, sync, invalidate };
  }
  const exported = { create, validate };
  if (typeof module !== "undefined" && module.exports) module.exports = exported;
  else root.FinanceIssueAdvice = exported;
})(typeof window !== "undefined" ? window : globalThis);
