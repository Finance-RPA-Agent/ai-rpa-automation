"use strict";
// Independent all-module replay. The original PR3 and R3B test files stay byte-identical.
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const source = path.resolve(__dirname, '../product/static');
const original = fs.readFileSync(path.join(__dirname, 'assistant-navigation.cjs'), 'utf8');
const instrumentedVm = {...vm, createContext(options) {
  const timers = new Map(); let id = 0;
  options.AbortController = AbortController;
  options.comboTimers = timers;
  options.setTimeout = (fn, ms) => { timers.set(++id, {fn, ms}); return id; };
  options.clearTimeout = id => timers.delete(id);
  const context = vm.createContext(options);
  // Load the actual reviewed third script, not a replacement advice controller.
  vm.runInContext(fs.readFileSync(path.join(source, 'issue-advice.js'), 'utf8'), context, {filename:'issue-advice.js'});
  return context;
}};
const outer = vm.createContext({require: name => name === 'node:vm' ? instrumentedVm : require(name),
  console, URL, process:{argv:['node','assistant-navigation.cjs','--source',source]}, __dirname,
  setImmediate, setTimeout, clearTimeout});
vm.runInContext(original.slice(0, original.indexOf('const EXPECTED_TESTS ='))+
  '\nglobalThis.expose={createHarness,tests,runningChat,completedChat};', outer);
const {createHarness,tests,runningChat} = outer.expose;
for (const scenario of tests) test('PR3 with actual advice module: '+scenario.name, {timeout:12000}, scenario.run);
const digest='a'.repeat(64);
const response=()=>({task_id:1,issue_id:'issue-a',revision:1,evidence_digest:digest,mode:'local_model',status:'advice_ready',
  status_message:'Synthetic validated selection',model:'qwen3.5:4b',advisory_only:true,
  facts:[{id:'F_FINDING',source:'rule',label:'Finding',value:'amount_mismatch'},
    {id:'F_AMOUNT_SOURCE',source:'input',label:'Source',value:'9007199254740993.01'}],
  explanation:'The cause is unknown.',selected_fact_ids:['F_FINDING','F_AMOUNT_SOURCE'],uncertainty:'ROOT_CAUSE_UNKNOWN',
  suggestions:[{id:'REVIEW_BOTH_SOURCES',text:'Independently verify both sources.',requires_human_decision:true}]});
async function harness(){
 const h=createHarness({hash:'#assistant/7',chats:[{id:7,title:'Synthetic A'}],details:{7:runningChat(7,11)}});await h.ready();
 assert.equal(vm.runInContext('typeof window.FinanceIssueAdvice.create',h.context),'function');
 setTask(h);return h;
}
function setTask(h,id=1){vm.runInContext(`S.route='task';S.tab='review';S.id=${id};S.token++;location.hash='#task/${id}//review';
 S.task={id:${id},status:'waiting_confirmation',revision:1,evidence_digest:'${digest}',issues:[{id:'issue-a',can_correct:true}]};issueAdvice.sync();`,h.context);}
const explain=h=>vm.runInContext('issueAdvice.explain("issue-a")',h.context);
const html=h=>vm.runInContext('issueAdvice.render("issue-a")',h.context);
function pending(h){const gate=h.hold('POST','/api/tasks/1/issues/issue-a/explanation');return {gate,done:explain(h)};}
test('three modules: no automatic request; duplicate click stays one, precision and human boundary',async()=>{
 const h=await harness();assert.equal(h.posts(/explanation$/).length,0);
 const p=pending(h);await p.gate.started;await explain(h);assert.equal(h.posts(/explanation$/).length,1);
 p.gate.respond(200,response());await p.done;
 assert.match(html(h),/9007199254740993\.01/);assert.match(html(h),/Human decision required/);
 assert.equal(h.posts(/\/(review|run|cancel)$/).length,0);
});
test('combined old advice 401 cannot clear new PR3 session or assistant memory',async()=>{
 const h=await harness(),p=pending(h);await p.gate.started;
 await h.clickAction('logout');h.context.location.hash='#assistant/7';await h.login('New Synthetic User');
 p.gate.respond(401,{detail:'Old account response'});await p.done;
 assert.equal(h.state().sessionUsername,'New Synthetic User');assert.equal(h.state().chatId,7);
 assert.doesNotMatch(h.html(),/Old account response/);
});
test('combined current advice 401 clears PR3 memory and advice',async()=>{
 const h=await harness(),p=pending(h);await p.gate.started;p.gate.respond(401,{detail:'Expired'});await p.done;
 assert.equal(h.state().sessionUsername,null);assert.equal(h.state().chatId,null);assert.equal(html(h),'');
});
test('combined old non-advice 401 still uses PR3 sessionEpoch guard',async()=>{
 const h=await harness(),g=h.hold('GET','/api/model');const p=vm.runInContext('api("/model")',h.context).catch(e=>e);
 await g.started;await h.clickAction('logout');h.context.location.hash='#assistant/7';await h.login('Next Synthetic User');
 g.respond(401,{detail:'Old'});await p;assert.equal(h.state().sessionUsername,'Next Synthetic User');assert.equal(h.state().chatId,7);
});
test('combined navigation A-B-A discards old advice and preserves long-running assistant',async()=>{
 const h=await harness(),p=pending(h);await p.gate.started;
 await h.navigate('#assistant/7');assert.equal(h.state().activeTurn,11);await h.navigate('#settings');await h.navigate('#assistant');
 assert.equal(h.state().chatId,7);assert.equal(h.posts(/turns$/).length,0);setTask(h,2);setTask(h,1);
 p.gate.respond(200,response());await p.done;assert.doesNotMatch(html(h),/Local AI ·/);
});
test('combined 409 retains session and shows evidence conflict',async()=>{
 const h=await harness(),p=pending(h);await p.gate.started;p.gate.respond(409,{detail:'Synthetic conflict'});await p.done;
 assert.match(html(h),/evidence has changed/);assert.equal(h.state().sessionUsername,'Fixture Owner');
});
test('combined page deadline rejects late success with no retry',async()=>{
 const h=await harness(),p=pending(h);await p.gate.started;
 const timer=[...h.context.comboTimers.values()].find(t=>t.ms===60000);assert.ok(timer);timer.fn();
 p.gate.respond(200,response());await p.done;assert.match(html(h),/timed out in the page/);assert.equal(h.posts(/explanation$/).length,1);
});
test('combined fallback remains separate from AI success',async()=>{
 const h=await harness(),p=pending(h);await p.gate.started;const d=response();Object.assign(d,{mode:'rules_only',status:'model_timeout',model:null});
 p.gate.respond(200,d);await p.done;assert.match(html(h),/Rule-based only/);assert.doesNotMatch(html(h),/Local AI ·/);
});
test('combined unknown authority and HTML remain non-executable',async()=>{
 const h=await harness(),p=pending(h);await p.gate.started;const d=response();d.advisory_only=false;d.approve='<script>pay()</script>';
 p.gate.respond(200,d);await p.done;assert.match(html(h),/could not be verified/);assert.doesNotMatch(html(h),/<script>|Local AI ·/);
});
test('assistant selection navigation discards pending financial advice',async()=>{
 const h=await harness(),p=pending(h);await p.gate.started;
 // The original PR harness exposes a minimal change target; missing matches is safe.
 await h.change('assistant-history','7');
 p.gate.respond(200,response());await p.done;assert.doesNotMatch(html(h),/Local AI ·/);
});
