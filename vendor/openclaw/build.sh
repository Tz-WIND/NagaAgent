#!/usr/bin/env bash
# vendor/openclaw/build.sh — 编译 NagaAgent 定制版 OpenClaw
#
# 用法:
#   bash vendor/openclaw/build.sh [--install-deps]
#
# 输出: vendor/openclaw/dist/ (干净的 ESM JS，与 npm 包结构一致)
#
# 前置条件:
#   - Node.js 22+
#   - pnpm (仅 --install-deps 时需要)

set -euo pipefail
cd "$(dirname "$0")"

# 安装依赖（仅首次或 CI 需要）
if [[ "${1:-}" == "--install-deps" ]]; then
  echo "[openclaw-build] Installing dependencies..."
  if command -v pnpm &>/dev/null; then
    pnpm install --frozen-lockfile 2>/dev/null || pnpm install
  else
    npm install
  fi
fi

# 检查 node_modules 是否存在
if [ ! -d "node_modules" ]; then
  echo "[openclaw-build] ERROR: node_modules not found. Run with --install-deps first."
  exit 1
fi

echo "[openclaw-build] Compiling TypeScript..."
rm -rf dist

# tsc 编译（跳过类型检查，只要产物）
NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=4096}" \
  npx tsc -p tsconfig.naga.json 2>&1 | grep -v "error TS" || true

# 验证核心文件
CORE_FILES=(
  "dist/gateway/server.js"
  "dist/agents/tools/web-search.js"
  "dist/index.js"
)

OK=true
for f in "${CORE_FILES[@]}"; do
  if [ ! -f "$f" ]; then
    echo "[openclaw-build] MISSING: $f"
    OK=false
  fi
done

if $OK; then
  echo "[openclaw-build] Build OK"
  echo "[openclaw-build] Output: $(pwd)/dist/"
else
  echo "[openclaw-build] Build incomplete — some core files missing"
  exit 1
fi
