import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { spawnSync } from 'node:child_process'

const cwd = process.cwd()
const bundledNode = resolve(cwd, 'backend-dist/runtime/node/bin/node')
const nodeExec = existsSync(bundledNode) ? bundledNode : process.execPath

const commands = [
  [resolve(cwd, 'node_modules/vue-tsc/bin/vue-tsc.js'), '-b'],
  [resolve(cwd, 'node_modules/vite/bin/vite.js'), 'build'],
]

for (const args of commands) {
  const result = spawnSync(nodeExec, args, {
    cwd,
    stdio: 'inherit',
  })

  if (result.error) {
    throw result.error
  }

  if (result.status !== 0) {
    process.exit(result.status ?? 1)
  }
}
