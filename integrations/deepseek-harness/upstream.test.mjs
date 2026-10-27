import test from 'node:test';
import assert from 'node:assert/strict';
import { Context } from '@deepseek-ai/cordis';
import { Session, SessionId } from '@deepseek-ai/dsh-session';
import { createUserMessage } from '@deepseek-ai/dsh-llm';
import { BasicCompactionEngine } from '@deepseek-ai/dsh-compaction-basic';
import { guardedCompactor, normalize } from './bridge.mjs';
import { apply } from './index.mjs';

test('published Harness Session event matches the capture contract', () => {
  const session=Session.create(SessionId('actual-host'));
  session.append('turn/start',{turn:1});
  const event=session.append('user/message',createUserMessage({
    content:[{type:'text',text:'这是实际宿主事件'}],source:{kind:'user'},
  }),{surfaceOp:'append'});
  assert.equal(normalize(event,'s','p')[0].text,'这是实际宿主事件');
  assert.equal(session.snapshotEvents(event.seq,event.seq+1)[0],event);
});

test('real BasicCompactionEngine calls the guarded summary boundary', async () => {
  const order=[];
  const ctx=new Context();
  ctx.provide('llm');
  ctx.set('llm',{async *stream(){
    order.push('llm');
    yield {type:'block-start',index:0,blockType:'text'};
    yield {type:'block-end',index:0,block:{type:'text',text:'整理照片'}};
  }});
  const capture={async flush(s,opts){order.push(opts.summary?'summary-write':'raw-write');}};
  const Guard=guardedCompactor(BasicCompactionEngine,capture);
  const engine=new Guard(ctx,{auto:false});
  const session=Session.create(SessionId('summary-contract'));
  const result=await engine.summarize({messages:[]},{session,options:{provider:'test',model:'test'}});
  assert.equal(result.summary[0].text,'整理照片');
  assert.deepEqual(order,['raw-write','llm','summary-write']);
  await ctx.fiber.dispose();
});

test('entry point registers lifecycle listeners and guarded backend', () => {
  const hooks=new Map(); let plugin;
  apply({on:(name,handler)=>hooks.set(name,handler),plugin:(value)=>{plugin=value;},logger:{warn(){}}},
    {command:'python',dataDir:'/tmp/unused',persona:'whale',project:'test',instanceId:'test',preset:'whale'});
  assert.ok(['session/created','session/event','session/flush','session/disposed','dispose'].every(k=>hooks.has(k)));
  assert.ok(plugin.prototype instanceof BasicCompactionEngine);
});

test('real Cordis session/flush awaits the Python durable write', async () => {
  const {mkdtemp,rm}=await import('node:fs/promises');
  const {tmpdir}=await import('node:os');
  const {join,resolve}=await import('node:path');
  const {SessionStore}=await import('@deepseek-ai/dsh-session');
  const {subprocess,sessionKey}=await import('./bridge.mjs');
  const dir=await mkdtemp(join(tmpdir(),'mlh-cordis-'));
  const ctx=new Context();
  const config={command:process.env.MLH_COMMAND??resolve('../../.venv/bin/memlikehuman'),
    dataDir:dir,persona:'whale',project:'test',instanceId:'actual',preset:'whale',compaction:{auto:false}};
  try {
    const sessions=new SessionStore(ctx);
    apply(ctx,config);
    const session=sessions.create(SessionId('real-lifecycle'),{meta:{agentPreset:'whale'}});
    session.append('turn/start',{turn:1});
    session.append('user/message',createUserMessage({
      content:[{type:'text',text:'真实事件总线的持久化测试'}],source:{kind:'user'},
    }),{surfaceOp:'append'});
    await sessions.flush(session);
    assert.equal((await subprocess(config,{session_id:sessionKey('actual',session.id)})).offset,session.seq);
  } finally {await ctx.fiber.dispose();await rm(dir,{recursive:true,force:true});}
});
