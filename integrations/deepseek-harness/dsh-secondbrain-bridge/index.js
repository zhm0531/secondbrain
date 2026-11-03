import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

export const name = 'dsh-secondbrain-bridge'
export const SECONDBRAIN_BRIDGE_SERVICE = 'secondBrainBridge'

export function apply(ctx) {
  const here = dirname(fileURLToPath(import.meta.url))
  ctx.provide(SECONDBRAIN_BRIDGE_SERVICE, {
    python: process.env.SECONDBRAIN_PYTHON ?? 'python',
    runner: join(here, 'scripts', 'secondbrain_mcp_server.py'),
    cwd: process.env.SECONDBRAIN_HOME ?? process.env.SECONDBRAIN_PROJECT ?? '',
    project: process.env.SECONDBRAIN_PROJECT ?? process.env.SECONDBRAIN_HOME ?? '',
    root: process.env.SECONDBRAIN_ROOT ?? 'memory',
    autostart: process.env.SECONDBRAIN_AUTOSTART ?? 'true',
    url: process.env.SECONDBRAIN_URL ?? 'http://127.0.0.1:8765',
  })
}
