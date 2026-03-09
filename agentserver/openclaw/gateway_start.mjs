/**
 * OpenClaw Gateway 最小启动脚本
 *
 * 由 NagaAgent 的 EmbeddedRuntime 通过 `node gateway_start.mjs` 拉起。
 * 直接调用 startGatewayServer()，跳过 CLI 层，启动更快、日志更干净。
 *
 * 环境变量：
 *   OPENCLAW_GATEWAY_PORT  — 端口号（默认 20789，避免与标准 openclaw 18789 冲突）
 */

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SERVER_REL = "node_modules/openclaw/dist/gateway/server.js";

// 按优先级查找 openclaw gateway/server.js
let serverPath = null;

const candidates = [
  // 打包模式：本脚本被复制到 runtime/gateway_start.mjs
  join(__dirname, "openclaw", SERVER_REL),
  // 开发模式：本脚本在 agentserver/openclaw/，runtime 在项目根 runtime/
  join(__dirname, "..", "..", "runtime", "openclaw", SERVER_REL),
];

for (const p of candidates) {
  if (existsSync(p)) { serverPath = p; break; }
}

// 兜底：npm 全局安装
if (!serverPath) {
  try {
    const globalRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf-8" }).trim();
    const p = join(globalRoot, "openclaw", "dist", "gateway", "server.js");
    if (existsSync(p)) serverPath = p;
  } catch {}
}

if (!serverPath) {
  process.stderr.write("[gateway_start] fatal: cannot find openclaw package\n");
  process.stderr.write(`[gateway_start] searched:\n${candidates.map(p => "  - " + p).join("\n")}\n`);
  process.exit(1);
}

process.stderr.write(`[gateway_start] using: ${serverPath}\n`);

const { startGatewayServer } = await import(pathToFileURL(serverPath).href);

const port = parseInt(process.env.OPENCLAW_GATEWAY_PORT || "20789", 10);
process.stdout.write(`[gateway_start] starting on port ${port}\n`);

try {
  const server = await startGatewayServer(port, {
    bind: "loopback",
    controlUiEnabled: false,
  });

  process.stdout.write(`[gateway_start] ready on port ${port}\n`);

  const shutdown = async (sig) => {
    process.stdout.write(`[gateway_start] received ${sig}, shutting down\n`);
    try { await server.close({ reason: `received ${sig}` }); } catch {}
    process.exit(0);
  };
  process.on("SIGTERM", () => shutdown("SIGTERM"));
  process.on("SIGINT", () => shutdown("SIGINT"));

} catch (err) {
  process.stderr.write(`[gateway_start] fatal: ${err}\n`);
  if (err.stack) process.stderr.write(err.stack + "\n");
  process.exit(1);
}
