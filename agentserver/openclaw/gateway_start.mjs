/**
 * OpenClaw Gateway 最小启动脚本
 *
 * 由 NagaAgent 的 EmbeddedRuntime 通过 `node gateway_start.mjs` 拉起。
 * 直接调用 startGatewayServer()，跳过 CLI 层，启动更快、日志更干净。
 *
 * 搜索顺序：
 *   1. 打包模式 — dist/ 与本脚本同目录（CI 预编译）
 *   2. 开发模式 — vendor/openclaw/dist/（手动编译或缓存）
 *   3. 开发模式 — vendor/openclaw/src/（tsx 直接跑源码，需 --import tsx）
 *
 * 环境变量：
 *   OPENCLAW_GATEWAY_PORT  — 端口号（默认 20789）
 */

import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

// 按优先级查找 gateway server 入口
let serverPath = null;

const candidates = [
  // 1. 打包模式：本脚本在 runtime/openclaw/gateway_start.mjs，dist 同目录
  join(__dirname, "dist", "gateway", "server.js"),
  // 2. 开发模式（已编译）：vendor/openclaw/dist/
  join(__dirname, "..", "..", "vendor", "openclaw", "dist", "gateway", "server.js"),
  // 3. 开发模式（源码）：vendor/openclaw/src/（需要 --import tsx）
  join(__dirname, "..", "..", "vendor", "openclaw", "src", "gateway", "server.ts"),
];

for (const p of candidates) {
  if (existsSync(p)) { serverPath = p; break; }
}

if (!serverPath) {
  process.stderr.write("[gateway_start] fatal: cannot find openclaw gateway entry\n");
  process.stderr.write(`[gateway_start] searched:\n${candidates.map(p => "  - " + p).join("\n")}\n`);
  process.exit(1);
}

const isTsSource = serverPath.endsWith(".ts");
if (isTsSource) {
  process.stderr.write(`[gateway_start] using source (tsx): ${serverPath}\n`);
} else {
  process.stderr.write(`[gateway_start] using compiled: ${serverPath}\n`);
}

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
