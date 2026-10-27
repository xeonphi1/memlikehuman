import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createCapture, guardedCompactor, normalize, subprocess, sessionKey } from './bridge.mjs';

const config = { command: process.env.MLH_COMMAND ?? resolve('../../.venv/bin/memlikehuman'),
  dataDir: '', persona: 'whale', project: 'companionship', instanceId: 'test', preset: 'whale' };
const user = (seq, text = '我现在住杭州') => ({type:'user/message', seq, time: 1767225600000 + seq,
  data:{source:{kind:'user'}, content:[{type:'text', text}]}});
const session = events => ({id:'chat', header:{agentPreset:'whale', createdAt:1767225600000},
  get seq() {return events.length;}, snapshotEvents:(start,end)=>events.slice(start,end)});

test('source fidelity, Unicode chunks, hidden reasoning and synthetic user exclusion', () => {
  assert.deepEqual(normalize({...user(0), data:{...user(0).data, source:{kind:'compact-checkpoint'}}}, 's', 'p'), []);
  const text = '鲸鱼🐳'.repeat(30000);
  assert.equal(normalize(user(0,text),'s','p').map(e=>e.text).join(''),text);
  const records = normalize({type:'assistant/message',seq:1,time:1767225600000,
    data:{message:{content:[{type:'reasoning',text:'hidden'}, {type:'text',text:'你好'}]}}},'s','p');
  assert.equal(records.length,1); assert.equal(records[0].text,'你好');
  assert.equal(records[0].role,'assistant');
});

test('compaction waits for both writes and does not summarize on failed preflight', async () => {
  const order=[];
  class Base { async summarize(){order.push('summarize'); return {summary:[{type:'text',text:'下一步整理照片'}]};} }
  const capture={async flush(s, options){order.push(options.summary ? 'summary-write' : 'raw-write');}};
  const Guard=guardedCompactor(Base,capture);
  await new Guard().summarize({}, {session:{}}, new AbortController().signal);
  assert.deepEqual(order,['raw-write','summarize','summary-write']);
  order.length=0;
  capture.flush=async()=>{throw new Error('disk full');};
  await assert.rejects(new Guard().summarize({}, {session:{}}), /disk full/);
  assert.deepEqual(order,[]);
  capture.flush=async(s,opts)=>{if(opts.summary) throw new Error('summary write failed');};
  await assert.rejects(new Guard().summarize({}, {session:{}}), /summary write failed/);
});

test('real Python bridge: restart, incremental capture, checkpoint, duplicate avoidance', async () => {
  const dir=await mkdtemp(join(tmpdir(),'mlh-host-'));
  const cfg={...config,dataDir:dir};
  try {
    const events=[user(0),{type:'assistant/message',seq:1,time:1767225600001,
      data:{message:{content:[{type:'text',text:'记住了，你现在住杭州。'}]}}}];
    const s=session(events);
    const capture=createCapture(cfg);
    await Promise.all([capture.flush(s),capture.flush(s,{checkpoint:true})]);
    const id=sessionKey(cfg.instanceId,s.id);
    assert.equal((await subprocess(cfg,{session_id:id})).offset,2);
    events.push(user(2,'下一步整理照片'));
    await createCapture(cfg).flush(s,{checkpoint:true,summary:'下一步整理照片'});
    const receipt=await subprocess(cfg,{session_id:id});
    assert.equal(receipt.offset,3); assert.match(receipt.covered_event_id,/dsh-summary/);
    const other=session([user(0)]); other.header.agentPreset='other';
    let calls=0;
    await createCapture(cfg,async()=>{calls++;}).flush(other);
    assert.equal(calls,0);
  } finally {await rm(dir,{recursive:true,force:true});}
});

test('transient failure retries without advancing the acknowledged cursor', async () => {
  let offset=0, fail=true;
  const capture=createCapture({...config,dataDir:'/unused'},async request=>{
    if(request.start===undefined) return {offset};
    if(fail){fail=false;throw new Error('offline');}
    offset=request.end;return {offset};
  });
  const s=session([user(0)]);
  await assert.rejects(capture.flush(s)); assert.equal(offset,0);
  await capture.flush(s);assert.equal(offset,1);
});
