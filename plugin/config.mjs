import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { isAbsolute, join } from 'node:path';
export const configPath = () => join(process.env.DSH_HOME || join(homedir(), '.dsh'), 'memlikehuman.json');
export function validate(config) {
  for (const key of ['command', 'dataDir', 'persona', 'project', 'preset', 'instanceId']) {
    if (typeof config[key] !== 'string' || !config[key].trim()) throw new Error(`Missing ${key}`);
  }
  for (const key of ['command', 'dataDir']) {
    if (!isAbsolute(config[key])) throw new Error(`${key} must be an absolute path`);
  }
  if (config.timeoutMs !== undefined && (!Number.isInteger(config.timeoutMs) || config.timeoutMs < 1000 || config.timeoutMs > 300000)) throw new Error('timeoutMs must be 1000..300000');
  return config;
}
export function loadConfig(path = configPath()) {
  let text;
  try { text = readFileSync(path, 'utf8'); } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
  return validate(JSON.parse(text));
}
