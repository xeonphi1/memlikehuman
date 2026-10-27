import * as mcp from '@deepseek-ai/dsh-mcp-client';
import { loadConfig } from './config.mjs';
export const name = 'memlikehuman-mcp';
export const inject = ['tools'];
export function apply(ctx, options = {}) {
  const config = loadConfig(options.configFile);
  if (!config) return;
  ctx.plugin(mcp, {
    serverName: 'memlikehuman', transport: 'stdio', command: config.command,
    args: ['--data-dir', config.dataDir, 'serve'],
    env: {MEMLIKEHUMAN_API_KEY: process.env.MEMLIKEHUMAN_API_KEY || ''},
    toolCallTimeoutMs: config.timeoutMs ?? 60000, failOnStartupError: true,
  });
}
