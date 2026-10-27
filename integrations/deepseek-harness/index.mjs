import { BasicCompactionEngine } from '@deepseek-ai/dsh-compaction-basic';
import { createCapture, guardedCompactor } from './bridge.mjs';

export const name = 'memlikehuman-host';
export const inject = ['sessions', 'llm', 'tokenMeter'];

export function apply(ctx, config) {
  const capture = createCapture(config);
  const timers = new Map();
  const pending = new Set();
  const report = () => ctx.logger.warn('MemLikeHuman capture failed; next flush retries from the saved cursor. Compaction is blocked until storage succeeds.');
  const flush = session => {
    clearTimeout(timers.get(session));
    timers.delete(session);
    const task = capture.flush(session);
    pending.add(task);
    task.then(() => pending.delete(task), () => pending.delete(task));
    return task;
  };
  ctx.on('session/created', session => {
    if (capture.selected(session)) void flush(session).catch(report);
  });
  ctx.on('session/event', (session, event) => {
    if (!['user/message', 'assistant/message', 'turn/end'].includes(event.type)) return;
    if (!capture.selected(session) || timers.has(session)) return;
    timers.set(session, setTimeout(() => { void flush(session).catch(report); }, 250));
  });
  ctx.on('session/flush', flush);
  ctx.on('session/disposed', session => { void flush(session).catch(report); });
  ctx.on('dispose', async () => {
    const sessions = [...timers.keys()];
    for (const timer of timers.values()) clearTimeout(timer);
    timers.clear();
    await Promise.all([...pending, ...sessions.map(session => capture.flush(session))]);
  });
  // Replaces the stock backend; preserves its automatic/manual/range logic.
  ctx.plugin(guardedCompactor(BasicCompactionEngine, capture), config.compaction ?? {});
}
