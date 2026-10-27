import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';

const hash = value => createHash('sha256').update(value).digest('hex');
export const sessionKey = (instance, id) => `dsh:${hash(`${instance}:${id}`)}`;

// Deliberately whitelist visible text. Never store reasoning, credentials in
// tool arguments, system prompts, or synthetic user-role injections as user speech.
export function normalize(event, sessionId, scopeKey) {
  let message, role;
  if (event.type === 'user/message' && event.data.source?.kind === 'user') {
    message = event.data; role = 'user';
  } else if (event.type === 'assistant/message') {
    message = event.data.message; role = 'assistant';
  } else return [];
  if (!Number.isSafeInteger(event.seq) || !Number.isFinite(event.time)) {
    throw new Error('Unsupported Harness event identity/time');
  }
  const records = [];
  for (const [blockIndex, block] of message.content.entries()) {
    if (block.type !== 'text' || !block.text) continue;
    // JS UTF-16 slices preserve every code unit after concatenation; avoid splitting pairs.
    const chunks = block.text.match(/[\s\S]{1,50000}(?![\uDC00-\uDFFF])/gu) ?? [];
    for (const [chunkIndex, text] of chunks.entries()) records.push({
      event_id: `dsh:${hash(`${scopeKey}:${sessionId}:${event.seq}:${blockIndex}:${chunkIndex}`)}`,
      session_id: sessionId, text, role,
      source: `deepseek-harness:event:${event.seq}:block:${blockIndex}:chunk:${chunkIndex}`,
      occurred_at: new Date(event.time).toISOString(),
    });
  }
  return records;
}

export function subprocess(config, payload) {
  return new Promise((resolve, reject) => {
    const child = spawn(config.command, [
      '--data-dir', config.dataDir, '--persona', config.persona,
      '--project', config.project, 'host-ingest',
    ], { shell: false, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true });
    let output = '', failed = false;
    const fail = () => { failed = true; child.kill(); reject(new Error('MemLikeHuman local write failed; inspect configuration and disk, then retry.')); };
    const timer = setTimeout(fail, config.timeoutMs ?? 60000);
    child.stdout.on('data', data => { output += data; if (output.length > 65536) fail(); });
    child.stderr.resume(); // Never log transcript-bearing validation or subprocess diagnostics.
    child.on('error', fail);
    child.stdin.on('error', fail);
    child.on('close', code => {
      clearTimeout(timer);
      if (failed) return;
      if (code !== 0) return fail();
      try { resolve(JSON.parse(output)); } catch { fail(); }
    });
    child.stdin.end(JSON.stringify(payload));
  });
}

export function createCapture(config, send = payload => subprocess(config, payload), select) {
  for (const field of ['command', 'dataDir', 'persona', 'project', 'instanceId', 'preset']) {
    if (typeof config[field] !== 'string' || !config[field]) throw new Error(`Missing ${field}`);
  }
  const states = new WeakMap();
  const selected = session => (select ? select(session) : session.header.agentPreset === config.preset) && session.header.origin !== 'subagent';
  async function drain(session, checkpoint, summary) {
    const id = sessionKey(config.instanceId, session.id);
    const scopeKey = `${config.persona}:${config.project}`;
    let receipt = await send({session_id: id});
    const target = session.seq;
    if (receipt.offset > target) throw new Error('Harness log is behind the saved memory cursor');
    while (receipt.offset < target) {
      const end = Math.min(target, receipt.offset + 50);
      const events = session.snapshotEvents(receipt.offset, end)
        .flatMap(event => normalize(event, id, scopeKey));
      receipt = await send({session_id: id, start: receipt.offset, end, events});
    }
    if (checkpoint) {
      const events = summary ? [{
        event_id: `dsh-summary:${hash(`${scopeKey}:${id}:${target}:${summary}`)}`,
        session_id: id, text: summary, role: 'assistant', category: 'reference',
        source: `deepseek-harness:compaction-summary:${target}`,
        // Stable across retries and distinct from the human message timestamp.
        occurred_at: new Date(session.snapshotEvents(Math.max(0, target - 1), target)[0]?.time ?? session.header.createdAt).toISOString(),
      }] : [];
      await send({session_id: id, start: target, end: target, events,
        checkpoint: true, ...(summary ? {summary_event_id: events[0].event_id} : {})});
    }
  }
  return {
    selected,
    flush(session, {checkpoint = false, summary} = {}) {
      if (!selected(session)) return Promise.resolve();
      const previous = states.get(session) ?? Promise.resolve();
      // A failed write remains retryable from the durable cursor on the next call.
      const next = previous.catch(() => {}).then(() => drain(session, checkpoint, summary));
      states.set(session, next);
      return next;
    },
  };
}

export function guardedCompactor(Base, capture) {
  return class MemoryCompactor extends Base {
    async summarize(input, agent, signal) {
      if (capture.selected && !capture.selected(agent.session)) return super.summarize(input, agent, signal);
      await capture.flush(agent.session, {checkpoint: true});
      signal?.throwIfAborted();
      const result = await super.summarize(input, agent, signal);
      const summary = result.summary.filter(b => b.type === 'text').map(b => b.text).join('\n');
      if (!summary || summary.length > 200000) throw new Error('Unsupported compaction summary size');
      await capture.flush(agent.session, {checkpoint: true, summary});
      signal?.throwIfAborted();
      return result; // Only now may Harness replace its context surface.
    }
  };
}
