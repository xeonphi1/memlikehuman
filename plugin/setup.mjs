#!/usr/bin/env node
import { mkdirSync, writeFileSync, renameSync, rmSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { parseArgs } from 'node:util';
import { configPath, loadConfig, validate } from './config.mjs';
try {
  const {values} = parseArgs({options: {
    command: {type:'string'}, 'data-dir': {type:'string'}, persona: {type:'string'},
    project: {type:'string'}, preset: {type:'string'}, 'instance-id': {type:'string'},
    help: {type:'boolean'},
  }});
  if (values.help) {
    console.log('memlikehuman-setup --command /absolute/path/to/memlikehuman --data-dir /private/memory [--persona whale --project companionship --preset whale]');
    console.log('Checks the Python bridge and saves local configuration under DSH_HOME (default ~/.dsh). Back up existing data before upgrading to schema v3.');
  } else {
    const path = configPath();
    const old = loadConfig(path);
    const config = validate({
      ...old,
      command: values.command ? resolve(values.command) : old?.command,
      dataDir: values['data-dir'] ? resolve(values['data-dir']) : old?.dataDir,
      persona: values.persona ?? old?.persona ?? 'whale',
      project: values.project ?? old?.project ?? 'companionship',
      preset: values.preset ?? old?.preset ?? 'whale',
      instanceId: values['instance-id'] ?? old?.instanceId ?? randomUUID(),
      timeoutMs: old?.timeoutMs ?? 60000,
    });
    const help = spawnSync(config.command, ['--help'], {encoding:'utf8', timeout:15000, windowsHide:true});
    if (help.status !== 0 || !help.stdout?.includes('host-ingest')) throw new Error('Python executable is unavailable or lacks host-ingest. Install the current Python package first.');
    const check = spawnSync(config.command, ['--data-dir', config.dataDir, 'doctor'], {encoding:'utf8', timeout:60000, windowsHide:true});
    if (check.status !== 0) throw new Error('Python doctor failed. Run it directly to inspect the database; configuration was not changed.');
    const health = JSON.parse(check.stdout);
    if (health.integrity !== 'ok' || health.foreign_key_errors?.length || health.schema_version !== 3) throw new Error('Python database health or schema check failed; configuration was not changed.');
    mkdirSync(dirname(path), {recursive:true});
    const temp = `${path}.${randomUUID()}.tmp`;
    try {
      writeFileSync(temp, JSON.stringify(config, null, 2)+'\n', {mode:0o600, flag:'wx'});
      renameSync(temp, path);
    } finally { rmSync(temp, {force:true}); }
    console.log(`Saved ${path}. Restart Harness. Scope: ${config.persona}/${config.project}; preset: ${config.preset}.`);
  }
} catch (error) { console.error(error.message); process.exitCode = 1; }
