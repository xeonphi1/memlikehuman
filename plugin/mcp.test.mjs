import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { apply } from './mcp.mjs';

test('MCP launcher uses the capture scope and host-managed recording instructions', () => {
  const home = mkdtempSync(join(tmpdir(), 'mlh-mcp-launch-'));
  const configFile = join(home, 'config.json');
  const config = {
    command: join(home, 'Python environment', 'memlikehuman'),
    dataDir: join(home, 'private memory'),
    persona: 'whale', project: 'companionship', preset: 'whale', instanceId: 'test',
  };
  writeFileSync(configFile, JSON.stringify(config));
  let options;
  try {
    apply({plugin: (_, value) => { options = value; }}, {configFile});
    assert.equal(options.command, config.command);
    assert.deepEqual(options.args, [
      '--data-dir', config.dataDir, '--persona', config.persona,
      '--project', config.project, 'serve', '--host-capture',
    ]);
    assert.equal(options.failOnStartupError, true);
    assert.equal(options.serverName, 'memlikehuman');
  } finally { rmSync(home, {recursive: true, force: true}); }
});
