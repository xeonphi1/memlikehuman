import { BasicCompactionEngine } from '@deepseek-ai/dsh-compaction-basic';
import { attachCapture } from '../integrations/deepseek-harness/index.mjs';
import { createCapture } from '../integrations/deepseek-harness/bridge.mjs';
import { loadConfig } from './config.mjs';
export const name = 'memlikehuman';
export const inject = ['sessions', 'agents', 'agentPresets'];
const guardOwner = Symbol.for('memlikehuman.compaction.guard');

// Wrap the existing instance, never the shared prototype. Preset-specific policies
// and service isolation remain owned by Harness. Disposal restores the exact method.
export function guardEngine(engine, capture) {
  if (!(engine instanceof BasicCompactionEngine)) throw new Error('MemLikeHuman requires the supported BasicCompactionEngine for this preset.');
  if (engine[guardOwner]) throw new Error('Duplicate MemLikeHuman compaction guard; remove the old plugin configuration.');
  const descriptor = Object.getOwnPropertyDescriptor(engine, 'summarize');
  const original = engine.summarize;
  async function guarded(input, agent, signal) {
    if (!capture.selected(agent.session)) return original.call(this, input, agent, signal);
    await capture.flush(agent.session, {checkpoint:true});
    signal?.throwIfAborted();
    const result = await original.call(this, input, agent, signal);
    const summary = result.summary.filter(block => block.type === 'text').map(block => block.text).join('\n');
    if (!summary || summary.length > 200000) throw new Error('Unsupported compaction summary size');
    await capture.flush(agent.session, {checkpoint:true, summary});
    signal?.throwIfAborted();
    return result;
  }
  engine.summarize = guarded;
  engine[guardOwner] = true;
  return () => {
    if (engine.summarize === guarded) {
      if (descriptor) Object.defineProperty(engine, 'summarize', descriptor);
      else delete engine.summarize;
    }
    delete engine[guardOwner];
  };
}
export function apply(ctx, options = {}) {
  const config = loadConfig(options.configFile);
  if (!config) {
    ctx.logger.warn('MemLikeHuman is not configured. Run memlikehuman-setup; automatic capture is inactive.');
    return;
  }
  const selections = new WeakMap();
  const capture = createCapture(config, undefined, session => {
    const agent = ctx.agents.get(session.id);
    const preset = (agent && ctx.agentPresets.composedPreset(agent.ctx)) ?? selections.get(session) ?? session.header.agentPreset;
    return preset === config.preset;
  });
  const engines = new Map();
  const bind = agent => {
    selections.set(agent.session, ctx.agentPresets.composedPreset(agent.ctx) ?? agent.session.header.agentPreset);
    if (!capture.selected(agent.session)) return;
    const engine = ctx.agentPresets.serviceFor(agent, 'compaction') ?? agent.ctx.get('compaction');
    if (!engines.has(engine)) engines.set(engine, guardEngine(engine, capture));
  };
  // Register restoration before mounting anything that can throw.
  ctx.on('dispose', () => { for (const restore of engines.values()) restore(); engines.clear(); });
  ctx.on('agent/created', ({agent}) => bind(agent));
  ctx.on('agent-preset/selected', id => { const agent = ctx.agents.get(id); if (agent) bind(agent); });
  for (const agent of ctx.agents.list()) bind(agent);
  attachCapture(ctx, capture);
}
