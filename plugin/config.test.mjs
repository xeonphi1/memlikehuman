import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { loadConfig } from './config.mjs';
import { apply, guardEngine } from './index.mjs';
import { BasicCompactionEngine } from '@deepseek-ai/dsh-compaction-basic';

test('unconfigured installation leaves the existing compactor untouched', () => {
  let mounted = false;
  apply({logger:{warn(){}},plugin:()=>{mounted=true;}}, {configFile:join(tmpdir(),`missing-${Date.now()}.json`)});
  assert.equal(mounted,false);
});
test('instance guard blocks failures, retains policy and restores the original method', async () => {
  const engine=Object.create(BasicCompactionEngine.prototype);
  const order=[];
  const original=async()=>{order.push('model');return {summary:[{type:'text',text:'next step'}]};};
  engine.summarize=original;
  let fail=false;
  const capture={selected:s=>s.selected, async flush(s,opts){order.push(opts.summary?'summary':'raw');if(fail)throw new Error('disk');}};
  const restore=guardEngine(engine,capture);
  assert.throws(()=>guardEngine(engine,capture),/Duplicate/);
  await engine.summarize({}, {session:{selected:true}});
  assert.deepEqual(order,['raw','model','summary']);
  order.length=0;fail=true;
  await assert.rejects(engine.summarize({}, {session:{selected:true}}),/disk/);
  assert.deepEqual(order,['raw']);
  order.length=0;
  await engine.summarize({}, {session:{selected:false}});
  assert.deepEqual(order,['model']);
  restore();assert.equal(engine.summarize,original);
});
test('setup validates Python, preserves installation identity, and rejects failed replacement', () => {
  const home=mkdtempSync(join(tmpdir(),'mlh-setup-'));
  const command=resolve(process.platform==='win32'?'.venv/Scripts/memlikehuman.exe':'.venv/bin/memlikehuman');
  const run=args=>spawnSync(process.execPath,['plugin/setup.mjs',...args],{encoding:'utf8',env:{...process.env,DSH_HOME:home}});
  try {
    const first=run(['--command',command,'--data-dir',join(home,'data')]);
    assert.equal(first.status,0,first.stderr);
    const path=join(home,'memlikehuman.json'); const config=loadConfig(path);
    assert.equal(run([]).status,0); assert.equal(loadConfig(path).instanceId,config.instanceId);
    const before=readFileSync(path,'utf8');
    assert.notEqual(run(['--command',join(home,'missing')]).status,0);
    assert.equal(readFileSync(path,'utf8'),before);
  } finally {rmSync(home,{recursive:true,force:true});}
});

test('configured bundle binds the existing isolated preset engine and restores it on unload', () => {
  const home=mkdtempSync(join(tmpdir(),'mlh-bind-'));
  const path=join(home,'config.json');
  writeFileSync(path,JSON.stringify({command:resolve('.venv/bin/memlikehuman'),dataDir:home,persona:'whale',project:'test',preset:'whale',instanceId:'test'}));
  const engine=Object.create(BasicCompactionEngine.prototype);
  const original=async()=>({summary:[]});engine.summarize=original;
  const agent={session:{id:'session',header:{agentPreset:'old'}},ctx:{get(){throw new Error('must use isolated engine');}}};
  const hooks=new Map();
  const ctx={on:(key,fn)=>{hooks.set(key,[...(hooks.get(key)??[]),fn]);},
    agents:{get:()=>agent,list:()=>[agent]},
    agentPresets:{composedPreset:()=> 'whale',serviceFor:()=>engine},logger:{warn(){}}};
  try {
    apply(ctx,{configFile:path});
    assert.notEqual(engine.summarize,original);
    hooks.get('agent/created')[0]({agent}); // shared engine is wrapped only once
    hooks.get('dispose')[0]();
    assert.equal(engine.summarize,original);
  } finally {rmSync(home,{recursive:true,force:true});}
});
