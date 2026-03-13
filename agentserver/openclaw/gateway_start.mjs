/**
 * OpenClaw Gateway 最小启动脚本
 *
 * 由 NagaAgent 的 EmbeddedRuntime 通过 `node gateway_start.mjs` 拉起。
 * 直接调用 startGatewayServer()，跳过 CLI 层，启动更快、日志更干净。
 *
 * 搜索顺序：
 *   默认 compiled-first：
 *     1. 打包模式 — dist/ 与本脚本同目录（CI 预编译）
 *     2. 开发模式 — vendor/openclaw/dist/（手动编译或缓存）
 *     3. 开发模式 — vendor/openclaw/src/（tsx 直接跑源码，需 --import tsx）
 *   source-first（开发调试）：
 *     1. vendor/openclaw/src/
 *     2. dist/
 *     3. vendor/openclaw/dist/
 *
 * 环境变量：
 *   OPENCLAW_GATEWAY_PORT  — 端口号（默认 20789）
 */

import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const preferSource =
  process.env.OPENCLAW_GATEWAY_ENTRY_MODE === "source"
  || process.execArgv.includes("tsx");

// 按优先级查找 gateway server 入口
let serverPath = null;
const packagedDist = join(__dirname, "dist", "gateway", "server.js");
const vendorDist = join(__dirname, "..", "..", "vendor", "openclaw", "dist", "gateway", "server.js");
const vendorSource = join(__dirname, "..", "..", "vendor", "openclaw", "src", "gateway", "server.ts");
const candidates = preferSource
  ? [
      vendorSource,
      packagedDist,
      vendorDist,
    ]
  : [
      packagedDist,
      vendorDist,
      vendorSource,
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
  process.stderr.write(`[gateway_start] entry mode: ${preferSource ? "source-first" : "compiled-first"}\n`);
  process.stderr.write(`[gateway_start] using source (tsx): ${serverPath}\n`);
} else {
  process.stderr.write(`[gateway_start] entry mode: ${preferSource ? "source-first" : "compiled-first"}\n`);
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
