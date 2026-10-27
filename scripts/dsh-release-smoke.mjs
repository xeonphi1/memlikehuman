import {writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {createUserMessage} from '@deepseek-ai/dsh-llm';
export const name='mlh-release-smoke';
export const inject=['agents','agentPresets','sessions','tools'];
export function apply(ctx) {
 if (!process.env.MLH_SMOKE_REPORT || !process.env.DSH_HOME) throw new Error('Use only with an isolated DSH_HOME and MLH_SMOKE_REPORT output path.');
 const timer=setTimeout(async()=>{
  let handle;
  try {
   handle=await ctx.agents.create({sessionId:`mlh-release-${Date.now()}`,meta:{agentPreset:'standard'},setup:async agentCtx=>{await ctx.agentPresets.mount(agentCtx,'standard');}});
   const agent=handle.agent;
   const engine=ctx.agentPresets.serviceFor(agent,'compaction');
   assert.equal(engine[Symbol.for('memlikehuman.compaction.guard')],true,'isolated preset guard is active');
   agent.session.append('turn/start',{turn:1});
   agent.session.append('user/message',createUserMessage({content:[{type:'text',text:'合成验收暗号：蓝鲸茶杯-731'}],source:{kind:'user'}}),{surfaceOp:'append'});
   await ctx.sessions.flush(agent.session);
   const tool=ctx.tools.get('mcp__memlikehuman__memory_recall');
   assert.ok(tool,'real MCP tool registration');
   const recall = await tool.execute({query:'蓝鲸茶杯-731',persona_id:'whale',project_id:'companionship'}, {signal:new AbortController().signal,agent});
   assert.ok(JSON.stringify(recall).includes('蓝鲸茶杯-731'),'real MCP read');
   writeFileSync(process.env.MLH_SMOKE_REPORT,JSON.stringify({ok:true,isolatedPresetGuard:true,mcpToolRegistered:true,mcpRecallVerified:true,sessionId:agent.session.id},null,2));
  } catch(error) {writeFileSync(process.env.MLH_SMOKE_REPORT,JSON.stringify({ok:false,error:String(error),stack:error.stack},null,2));}
  finally {await handle?.dispose();}
 },2500);
 ctx.on('dispose',()=>clearTimeout(timer));
}
