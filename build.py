#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NagaAgent 跨平台构建脚本（Windows / macOS / Linux）

流程：
  1. 环境检查（Python, uv, Node.js, npm）
  2. 同步 Python 依赖 + build 组（pyinstaller）
  3. 准备 OpenClaw 运行时（下载 Node.js 便携版 + 预装 OpenClaw/Agent Browser）
  4. PyInstaller 编译 Python 后端
  5. Electron 前端构建 + 打包
  6. 输出汇总

默认在构建阶段预装 OpenClaw 与 Agent Browser，用户安装后首次启动可直接使用。

用法:
  python scripts/build.py                  # 完整构建（自动检测平台）
  python scripts/build.py --skip-openclaw  # 跳过 OpenClaw 运行时准备
  python scripts/build.py --backend-only   # 仅编译后端
  python scripts/build.py --force-openclaw # 强制重装 OpenClaw
  python scripts/build.py --debug          # 调试模式（仅 Windows 生效）
"""

import os
import sys
import platform
import shutil
import subprocess
import argparse
import time
import re
import zipfile
import tarfile
import json
from urllib.parse import unquote, urlparse
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # Python < 3.11 fallback
import urllib.request
from pathlib import Path
from typing import Optional

# ============ 平台检测 ============

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
PLATFORM_TAG = "win" if IS_WINDOWS else "mac" if IS_MACOS else "linux"

# macOS: 区分 arm64 (Apple Silicon) 和 x86_64 (Intel)
MAC_ARCH = "arm64" if platform.machine() == "arm64" else "x64"

# ============ 常量 ============

PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
BACKEND_DIST_DIR = FRONTEND_DIR / "backend-dist"
RUNTIME_DIR = BACKEND_DIST_DIR / "runtime"
NODE_RUNTIME_DIR = RUNTIME_DIR / "node"
OPENCLAW_RUNTIME_DIR = RUNTIME_DIR / "openclaw"
PYTHON_RUNTIME_DIR = RUNTIME_DIR / "python"
SPEC_FILE = PROJECT_ROOT / "naga-backend.spec"
AGENT_BROWSER_NPM_SPEC = "agent-browser"

# 最低版本要求
MIN_NODE_MAJOR = 22
MIN_PYTHON = (3, 11)

# OpenClaw 运行时版本
NODE_VERSION = "22.13.1"
PYTHON_RUNTIME_VERSION = "3.11.15"
PYTHON_RUNTIME_RELEASE = "20260303"
CACHE_DIR = PROJECT_ROOT / ".cache"

# Node.js 下载地址（按平台）
if IS_WINDOWS:
    NODE_ARCHIVE = f"node-v{NODE_VERSION}-win-x64.zip"
elif IS_MACOS:
    NODE_ARCHIVE = f"node-v{NODE_VERSION}-darwin-{MAC_ARCH}.tar.gz"
else:
    NODE_ARCHIVE = f"node-v{NODE_VERSION}-linux-x64.tar.xz"

NODE_DIST_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/{NODE_ARCHIVE}"

# Python standalone 运行时（用于外部 Python MCP）
if IS_WINDOWS:
    PYTHON_ARCHIVE = (
        f"cpython-{PYTHON_RUNTIME_VERSION}+{PYTHON_RUNTIME_RELEASE}"
        "-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
    )
elif IS_MACOS:
    _py_arch = "aarch64" if MAC_ARCH == "arm64" else "x86_64"
    PYTHON_ARCHIVE = (
        f"cpython-{PYTHON_RUNTIME_VERSION}+{PYTHON_RUNTIME_RELEASE}"
        f"-{_py_arch}-apple-darwin-install_only_stripped.tar.gz"
    )
else:
    PYTHON_ARCHIVE = (
        f"cpython-{PYTHON_RUNTIME_VERSION}+{PYTHON_RUNTIME_RELEASE}"
        "-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
    )

PYTHON_DIST_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    f"{PYTHON_RUNTIME_RELEASE}/{PYTHON_ARCHIVE}"
)

# uv standalone 二进制版本与下载地址
UV_VERSION = "0.6.6"
UV_RUNTIME_DIR = RUNTIME_DIR / "uv"
if IS_WINDOWS:
    UV_ARCHIVE = "uv-x86_64-pc-windows-msvc.zip"
elif IS_MACOS:
    _uv_arch = "aarch64" if MAC_ARCH == "arm64" else "x86_64"
    UV_ARCHIVE = f"uv-{_uv_arch}-apple-darwin.tar.gz"
else:
    UV_ARCHIVE = "uv-x86_64-unknown-linux-gnu.tar.gz"
UV_DIST_URL = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/{UV_ARCHIVE}"

# 平台相关路径
NODE_BIN = "node.exe" if IS_WINDOWS else "bin/node"
NPM_BIN = "npm.cmd" if IS_WINDOWS else "bin/npm"
BACKEND_EXT = ".exe" if IS_WINDOWS else ""
INSTALLER_GLOB = "*.exe" if IS_WINDOWS else "*.dmg" if IS_MACOS else "*.AppImage"


def safe_print(*values: object, sep: str = " ", end: str = "\n", file=None) -> None:
    stream = file or sys.stdout
    text = sep.join(str(value) for value in values)
    try:
        print(text, end=end, file=stream, flush=True)
        return
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "utf-8"
        fallback = text.encode(encoding, errors="backslashreplace").decode(encoding, errors="strict")
        stream.write(fallback)
        stream.write(end)
        stream.flush()


def read_version() -> str:
    """从 pyproject.toml 读取版本号（唯一版本源）"""
    with open(PROJECT_ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["version"]


def sync_frontend_version() -> None:
    """将 pyproject.toml 版本同步到 package.json（electron-builder 用它生成安装包文件名）"""
    ver = read_version()
    pkg_path = FRONTEND_DIR / "package.json"
    pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    if pkg.get("version") == ver:
        return
    pkg["version"] = ver
    pkg_path.write_text(json.dumps(pkg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"已同步版本 {ver} → package.json")


def log(msg: str) -> None:
    safe_print(f"[build] {msg}")


def log_step(step: int, total: int, title: str) -> None:
    safe_print()
    safe_print(f"{'=' * 50}")
    safe_print(f"  Step {step}/{total}: {title}")
    safe_print(f"{'=' * 50}")


def run(
    cmd: list[str],
    cwd: Optional[Path] = None,
    env: Optional[dict[str, str]] = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """执行命令并实时输出。自动通过 shutil.which 解析 .cmd/.bat（Windows）"""
    resolved = shutil.which(cmd[0])
    if resolved:
        cmd = [resolved, *cmd[1:]]
    log(f"$ {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        check=check,
    )


def get_cmd_version(cmd: str, args: list[str] | None = None) -> Optional[str]:
    """获取命令版本号，失败返回 None。通过 shutil.which 解析 .cmd/.bat"""
    resolved = shutil.which(cmd)
    if not resolved:
        return None
    try:
        result = subprocess.run(
            [resolved, *(args or ["--version"])],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


# ============ Step 1: 环境检查 ============


def check_environment() -> bool:
    """检查构建所需的工具是否就绪"""
    ok = True

    platform_name = "Windows" if IS_WINDOWS else "macOS" if IS_MACOS else "Linux"
    log(f"  平台: {platform_name} ({platform.machine()})  ✓")
    log(f"  构建版本: {read_version()}")

    # Python 版本
    py_ver = sys.version_info[:2]
    if py_ver >= MIN_PYTHON:
        log(f"  Python {sys.version.split()[0]}  ✓")
    else:
        log(f"  Python {sys.version.split()[0]}  ✗  (需要 >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})")
        ok = False

    # uv
    uv_ver = get_cmd_version("uv", ["-V"])
    if uv_ver:
        log(f"  {uv_ver}  ✓")
    else:
        log("  uv 未安装  ✗  (pip install uv)")
        ok = False

    # Node.js
    node_ver = get_cmd_version("node")
    if node_ver:
        major = int(node_ver.lstrip("v").split(".")[0])
        status = "✓" if major >= MIN_NODE_MAJOR else f"✗  (需要 >= {MIN_NODE_MAJOR})"
        log(f"  Node.js {node_ver}  {status}")
        if major < MIN_NODE_MAJOR:
            ok = False
    else:
        log(f"  Node.js 未安装  ✗  (需要 >= {MIN_NODE_MAJOR})")
        ok = False

    # npm
    npm_ver = get_cmd_version("npm")
    if npm_ver:
        log(f"  npm {npm_ver}  ✓")
    else:
        log("  npm 未安装  ✗")
        ok = False

    return ok


# ============ Step 2: 同步依赖 ============


def sync_dependencies() -> None:
    """uv sync + build 依赖组"""
    run(["uv", "sync", "--group", "build"], cwd=PROJECT_ROOT)
    log("Python 依赖同步完成")


# ============ Step 3: 准备 OpenClaw 运行时 ============


def download_node_runtime() -> Path:
    """下载 Node.js 便携版，返回本地缓存路径"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = CACHE_DIR / NODE_ARCHIVE

    if archive_path.exists():
        log(f"使用缓存 Node.js 包: {archive_path}")
        return archive_path

    log(f"下载 Node.js v{NODE_VERSION}: {NODE_DIST_URL}")
    urllib.request.urlretrieve(NODE_DIST_URL, str(archive_path))
    log(f"Node.js 下载完成: {archive_path} ({archive_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return archive_path


def _extract_zip(archive_path: Path) -> None:
    """解压 .zip 格式的 Node.js（Windows）"""
    prefix = f"node-v{NODE_VERSION}-win-x64/"
    with zipfile.ZipFile(archive_path, "r") as zf:
        for member in zf.infolist():
            if not member.filename.startswith(prefix):
                continue
            rel = member.filename[len(prefix):]
            if not rel:
                continue
            target = NODE_RUNTIME_DIR / rel
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)


def _extract_prefixed_tarball(archive_path: Path, prefix: str, target_root: Path) -> None:
    mode = "r:gz" if archive_path.name.endswith(".tar.gz") else "r:xz"
    with tarfile.open(archive_path, mode) as tf:
        for member in tf.getmembers():
            if not member.name.startswith(prefix):
                continue
            rel = member.name[len(prefix):]
            if not rel:
                continue
            target = target_root / rel
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.issym():
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() or target.is_symlink():
                    target.unlink()
                os.symlink(member.linkname, target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                extracted = tf.extractfile(member)
                if extracted:
                    with open(target, "wb") as dst:
                        shutil.copyfileobj(extracted, dst)
                    if member.mode & 0o111:
                        target.chmod(target.stat().st_mode | 0o755)


def _extract_tarball(archive_path: Path) -> None:
    """解压 .tar.gz / .tar.xz 格式的 Node.js（macOS / Linux）"""
    # 推断 archive 内的顶层目录名
    stem = NODE_ARCHIVE
    for suffix in (".tar.gz", ".tar.xz"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    prefix = f"{stem}/"

    _extract_prefixed_tarball(archive_path, prefix, NODE_RUNTIME_DIR)


def extract_node_runtime(archive_path: Path) -> None:
    """解压 Node.js 到 runtime/node"""
    if NODE_RUNTIME_DIR.exists():
        log(f"清理旧 Node.js 运行时: {NODE_RUNTIME_DIR}")
        shutil.rmtree(NODE_RUNTIME_DIR)

    NODE_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    log(f"解压 Node.js 到: {NODE_RUNTIME_DIR}")
    if archive_path.suffix == ".zip":
        _extract_zip(archive_path)
    else:
        _extract_tarball(archive_path)

    # 验证关键文件
    node_bin = NODE_RUNTIME_DIR / NODE_BIN
    npm_bin = NODE_RUNTIME_DIR / NPM_BIN
    if not node_bin.exists():
        raise FileNotFoundError(f"解压后缺少 node: {node_bin}")
    if not npm_bin.exists():
        raise FileNotFoundError(f"解压后缺少 npm: {npm_bin}")
    log("Node.js 便携版解压完成")


def _find_runtime_npm_cli() -> Path:
    candidates = [
        NODE_RUNTIME_DIR / "node_modules" / "npm" / "bin" / "npm-cli.js",
        NODE_RUNTIME_DIR / "node_modules" / "npm" / "bin" / "npm-cli.mjs",
        NODE_RUNTIME_DIR / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js",
        NODE_RUNTIME_DIR / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.mjs",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Node runtime 中未找到 npm-cli.js: {NODE_RUNTIME_DIR}")


def _find_vendor_typescript_cli(vendor_root: Path) -> Path:
    candidates = [
        vendor_root / "node_modules" / "typescript" / "bin" / "tsc",
        vendor_root / "node_modules" / "typescript" / "bin" / "tsc.js",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"vendor/openclaw 中未找到 TypeScript CLI: {vendor_root / 'node_modules' / 'typescript'}")


def _runtime_npm_command(*args: str) -> list[str]:
    node_bin = NODE_RUNTIME_DIR / NODE_BIN
    if not node_bin.exists():
        raise FileNotFoundError(f"node 不存在: {node_bin}")
    npm_cli = _find_runtime_npm_cli()
    return [str(node_bin), str(npm_cli), *args]


def _apply_runtime_npm_env(env: dict[str, str]) -> dict[str, str]:
    npm_cache_dir = CACHE_DIR / "npm"
    npm_cache_dir.mkdir(parents=True, exist_ok=True)
    env["NPM_CONFIG_CACHE"] = str(npm_cache_dir)
    return env


def _install_openclaw_vendor_dependencies(vendor_root: Path, env: dict[str, str], force: bool) -> None:
    node_modules_dir = vendor_root / "node_modules"
    package_lock = vendor_root / "package-lock.json"

    if force and node_modules_dir.exists():
        log(f"强制重建 vendor/openclaw 依赖: {node_modules_dir}")
        shutil.rmtree(node_modules_dir)

    if node_modules_dir.exists():
        return

    install_attempts = [["ci"], ["install"]] if package_lock.exists() else [["install"]]
    last_error: Optional[subprocess.CalledProcessError] = None
    for index, install_args in enumerate(install_attempts):
        install_desc = " ".join(install_args)
        if index == 0:
            log(f"安装 vendor/openclaw 依赖（{install_desc}，启用平台脚本）...")
        else:
            log(f"vendor/openclaw 依赖安装回退到 `{install_desc}`（锁文件与平台原生包可能不完全同步）...")
        try:
            run(
                _runtime_npm_command(*install_args),
                cwd=vendor_root,
                env=env,
            )
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            if index == len(install_attempts) - 1:
                raise
    if last_error is not None:
        raise last_error


def _write_openclaw_import_diagnostics(output: str) -> Optional[Path]:
    if not output.strip():
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    diag_path = CACHE_DIR / "openclaw-gateway-import.log"
    diag_path.write_text(output, encoding="utf-8")
    return diag_path


_MISSING_MODULE_RE = re.compile(r"Cannot find module ['\"](?P<path>[^'\"]+)['\"]")


def _resolve_missing_module_target(raw_path: str) -> Optional[Path]:
    raw = raw_path.strip()
    if not raw:
        return None
    if raw.startswith("file://"):
        parsed = urlparse(raw)
        raw = unquote(parsed.path)
        if IS_WINDOWS and re.match(r"^/[A-Za-z]:", raw):
            raw = raw[1:]
    try:
        return Path(raw).resolve()
    except Exception:
        return None


def _find_openclaw_source_candidate(vendor_root: Path, runtime_relative_path: Path) -> Optional[Path]:
    source_root = vendor_root / "src"
    stem = runtime_relative_path.with_suffix("")
    for suffix in (".ts", ".tsx", ".mts", ".cts", ".js", ".mjs", ".cjs", ".json"):
        candidate = source_root / stem.with_suffix(suffix)
        if candidate.exists():
            return candidate
    return None


def _transpile_openclaw_source_module(
    node_bin: Path,
    vendor_root: Path,
    source_path: Path,
    output_path: Path,
    env: dict[str, str],
) -> None:
    typescript_lib = vendor_root / "node_modules" / "typescript" / "lib" / "typescript.js"
    tsconfig_path = vendor_root / "tsconfig.naga.json"
    if not typescript_lib.exists():
        raise FileNotFoundError(f"缺少 TypeScript 运行库: {typescript_lib}")
    if not tsconfig_path.exists():
        raise FileNotFoundError(f"缺少 tsconfig.naga.json: {tsconfig_path}")

    script = (
        "const fs = require('node:fs');"
        "const path = require('node:path');"
        "const [tsLibPath, tsconfigPath, srcPath, outPath] = process.argv.slice(1);"
        "const ts = require(tsLibPath);"
        "const configFile = ts.readConfigFile(tsconfigPath, ts.sys.readFile);"
        "if (configFile.error) {"
        "  throw new Error(ts.flattenDiagnosticMessageText(configFile.error.messageText, '\\n'));"
        "}"
        "const parsed = ts.parseJsonConfigFileContent(configFile.config, ts.sys, path.dirname(tsconfigPath));"
        "const source = fs.readFileSync(srcPath, 'utf8');"
        "const output = ts.transpileModule(source, {"
        "  compilerOptions: {"
        "    ...parsed.options,"
        "    module: ts.ModuleKind.ESNext,"
        "    noEmit: false,"
        "    declaration: false,"
        "    sourceMap: false,"
        "    inlineSourceMap: false,"
        "    inlineSources: false,"
        "    verbatimModuleSyntax: true"
        "  },"
        "  fileName: srcPath,"
        "  reportDiagnostics: true"
        "});"
        "fs.mkdirSync(path.dirname(outPath), { recursive: true });"
        "fs.writeFileSync(outPath, output.outputText, 'utf8');"
        "const errors = (output.diagnostics || []).filter((d) => d.category === ts.DiagnosticCategory.Error);"
        "if (errors.length > 0) {"
        "  const summary = errors.slice(0, 5)"
        "    .map((d) => ts.flattenDiagnosticMessageText(d.messageText, '\\n'))"
        "    .join('\\n');"
        "  console.error(summary);"
        "}"
    )
    result = subprocess.run(
        [str(node_bin), "-e", script, str(typescript_lib), str(tsconfig_path), str(source_path), str(output_path)],
        cwd=vendor_root,
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        raise RuntimeError(
            f"补齐 OpenClaw 模块失败: {source_path} -> {output_path}"
            + (f"\n{output}" if output else "")
        )


def _hydrate_missing_openclaw_runtime_module(
    node_bin: Path,
    vendor_root: Path,
    missing_target: Path,
    env: dict[str, str],
) -> bool:
    runtime_dist_root = (OPENCLAW_RUNTIME_DIR / "dist").resolve()
    try:
        relative_path = missing_target.relative_to(runtime_dist_root)
    except ValueError:
        return False

    vendor_dist_candidate = vendor_root / "dist" / relative_path
    if vendor_dist_candidate.exists():
        missing_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(vendor_dist_candidate, missing_target)
        log(f"已从 vendor/dist 补齐缺失模块: {relative_path.as_posix()}")
        return True

    source_candidate = _find_openclaw_source_candidate(vendor_root, relative_path)
    if source_candidate is None:
        return False

    missing_target.parent.mkdir(parents=True, exist_ok=True)
    if source_candidate.suffix == ".json":
        shutil.copy2(source_candidate, missing_target)
    elif source_candidate.suffix in {".js", ".mjs", ".cjs"}:
        shutil.copy2(source_candidate, missing_target)
    else:
        _transpile_openclaw_source_module(node_bin, vendor_root, source_candidate, missing_target, env)
    log(
        "已从源码补齐缺失模块: "
        f"{relative_path.as_posix()} <- {source_candidate.relative_to(vendor_root).as_posix()}"
    )
    return True


def _verify_openclaw_runtime_import(node_bin: Path, env: dict[str, str], vendor_root: Path) -> None:
    verify_script = (
        "import { resolve } from 'node:path';"
        "import { pathToFileURL } from 'node:url';"
        "const target = pathToFileURL(resolve('dist/gateway/server.js')).href;"
        "await import(target);"
        "console.log('openclaw-gateway-import-ok');"
    )
    repaired_targets: set[Path] = set()
    for _ in range(12):
        result = subprocess.run(
            [str(node_bin), "--input-type=module", "-e", verify_script],
            cwd=OPENCLAW_RUNTIME_DIR,
            env=env,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
        if result.returncode == 0:
            log("OpenClaw Gateway 导入校验通过")
            return

        output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        missing_match = _MISSING_MODULE_RE.search(output or "")
        missing_target = (
            _resolve_missing_module_target(missing_match.group("path"))
            if missing_match is not None
            else None
        )
        if (
            missing_target is not None
            and missing_target not in repaired_targets
            and _hydrate_missing_openclaw_runtime_module(node_bin, vendor_root, missing_target, env)
        ):
            repaired_targets.add(missing_target)
            _rewrite_openclaw_dist_import_suffixes(OPENCLAW_RUNTIME_DIR / "dist")
            log(f"OpenClaw Gateway 导入校验发现缺失模块，已补齐后重试: {missing_target}")
            continue

        diag_path = _write_openclaw_import_diagnostics(output) if output else None
        if diag_path:
            log(f"OpenClaw Gateway 导入校验失败，日志已写入 {diag_path}")
            _log_openclaw_tsc_excerpt(output)
        raise RuntimeError("OpenClaw Gateway 导入校验失败")

    raise RuntimeError("OpenClaw Gateway 导入校验失败：缺失模块补齐重试次数已达上限")


def download_python_runtime() -> Path:
    """下载最小 Python standalone 运行时，返回本地缓存路径"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = CACHE_DIR / PYTHON_ARCHIVE
    if archive_path.exists():
        log(f"使用缓存 Python standalone 包: {archive_path}")
        return archive_path
    log(f"下载 Python standalone {PYTHON_RUNTIME_VERSION}: {PYTHON_DIST_URL}")
    urllib.request.urlretrieve(PYTHON_DIST_URL, str(archive_path))
    log(f"Python standalone 下载完成: {archive_path} ({archive_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return archive_path


def _write_unix_python_shim(path: Path, target_name: str) -> None:
    path.write_text(
        "#!/bin/sh\n"
        'SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"\n'
        f'exec "$SCRIPT_DIR/{target_name}" "$@"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_unix_pip_shim(path: Path) -> None:
    path.write_text(
        "#!/bin/sh\n"
        'SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"\n'
        'exec "$SCRIPT_DIR/python" -m pip "$@"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_windows_pip_shim(path: Path) -> None:
    path.write_text("@echo off\r\n\"%~dp0python.exe\" -m pip %*\r\n", encoding="utf-8")


def _find_extracted_python_binary() -> Path:
    candidates = []
    if IS_WINDOWS:
        candidates.extend(
            [
                PYTHON_RUNTIME_DIR / "python.exe",
                PYTHON_RUNTIME_DIR / "bin" / "python.exe",
            ]
        )
    else:
        candidates.extend(
            [
                PYTHON_RUNTIME_DIR / "bin" / "python",
                PYTHON_RUNTIME_DIR / "bin" / f"python{PYTHON_RUNTIME_VERSION[:4]}",
                PYTHON_RUNTIME_DIR / "bin" / "python3",
            ]
        )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Python standalone 解压后未找到解释器: {PYTHON_RUNTIME_DIR}")


def _path_size_bytes(path: Path) -> int:
    if not path.exists() and not path.is_symlink():
        return 0
    if path.is_file() or path.is_symlink():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for candidate in path.rglob("*"):
        try:
            if candidate.is_file() and not candidate.is_symlink():
                total += candidate.stat().st_size
        except OSError:
            continue
    return total


def _remove_path(path: Path) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
        return True
    path.unlink()
    return True


def _python_stdlib_roots() -> list[Path]:
    roots: list[Path] = []
    for candidate in sorted(PYTHON_RUNTIME_DIR.glob("lib/python3.*")):
        if candidate.is_dir():
            roots.append(candidate)
    lib_dir = PYTHON_RUNTIME_DIR / "Lib"
    if lib_dir.is_dir():
        roots.append(lib_dir)
    return roots


def _materialize_python_shims() -> None:
    python_bin = _find_extracted_python_binary()
    if IS_WINDOWS:
        root = python_bin.parent
        pip_cmd = root / "pip.cmd"
        pip3_cmd = root / "pip3.cmd"
        if not pip_cmd.exists():
            _write_windows_pip_shim(pip_cmd)
        if not pip3_cmd.exists():
            _write_windows_pip_shim(pip3_cmd)
        python3_exe = root / "python3.exe"
        if not python3_exe.exists():
            shutil.copy2(python_bin, python3_exe)
        return

    bin_dir = python_bin.parent
    python_name = python_bin.name
    for shim_name in ("python", "python3"):
        shim_path = bin_dir / shim_name
        if shim_path.exists():
            continue
        _write_unix_python_shim(shim_path, python_name)
    for shim_name in ("pip", "pip3"):
        shim_path = bin_dir / shim_name
        if shim_path.exists():
            continue
        _write_unix_pip_shim(shim_path)


def _prune_python_runtime() -> None:
    """裁剪 Python standalone 中与 MCP 运行无关的开发/GUI组件。"""
    before_bytes = _path_size_bytes(PYTHON_RUNTIME_DIR)
    removed_paths: list[str] = []

    def drop(path: Path) -> None:
        if _remove_path(path):
            removed_paths.append(path.relative_to(PYTHON_RUNTIME_DIR).as_posix())

    for rel in ("include", "share", "lib/pkgconfig"):
        drop(PYTHON_RUNTIME_DIR / rel)

    bin_dir = _find_extracted_python_binary().parent
    for pattern in ("2to3*", "idle3*", "pydoc3*", "python*-config"):
        for candidate in sorted(bin_dir.glob(pattern)):
            drop(candidate)

    for pattern in (
        "lib/libtcl*",
        "lib/libtk*",
        "lib/tcl*",
        "lib/tk*",
        "lib/itcl*",
        "lib/thread*",
        "DLLs/tcl*.dll",
        "DLLs/tk*.dll",
    ):
        for candidate in sorted(PYTHON_RUNTIME_DIR.glob(pattern)):
            drop(candidate)

    for stdlib_root in _python_stdlib_roots():
        for rel in (
            "idlelib",
            "tkinter",
            "turtledemo",
            "__phello__",
            "ensurepip",
            "lib2to3",
            "pydoc_data",
            "test",
            "tests",
            "turtle.py",
            "pydoc.py",
        ):
            candidate = stdlib_root / rel
            if _remove_path(candidate):
                removed_paths.append(candidate.relative_to(PYTHON_RUNTIME_DIR).as_posix())
        for candidate in sorted(stdlib_root.glob("config-*")):
            if _remove_path(candidate):
                removed_paths.append(candidate.relative_to(PYTHON_RUNTIME_DIR).as_posix())
        lib_dynload = stdlib_root / "lib-dynload"
        if lib_dynload.is_dir():
            for pattern in ("_tkinter*", "_test*", "_ctypes_test*", "xxlimited*"):
                for candidate in sorted(lib_dynload.glob(pattern)):
                    if _remove_path(candidate):
                        removed_paths.append(candidate.relative_to(PYTHON_RUNTIME_DIR).as_posix())
        site_packages = stdlib_root / "site-packages"
        if site_packages.is_dir():
            for rel in ("pkg_resources/tests", "pkg_resources/api_tests.txt", "setuptools/tests"):
                candidate = site_packages / rel
                if _remove_path(candidate):
                    removed_paths.append(candidate.relative_to(PYTHON_RUNTIME_DIR).as_posix())

    after_bytes = _path_size_bytes(PYTHON_RUNTIME_DIR)
    removed_mb = max(before_bytes - after_bytes, 0) / 1024 / 1024
    log(
        "Python MCP 运行时裁剪完成: "
        f"-{removed_mb:.1f} MB"
        + (f" ({len(removed_paths)} 项)" if removed_paths else " (无可裁剪项)")
    )


def extract_python_runtime(archive_path: Path) -> None:
    """解压 Python standalone 到 runtime/python/"""
    if PYTHON_RUNTIME_DIR.exists():
        log(f"清理旧 Python 运行时: {PYTHON_RUNTIME_DIR}")
        shutil.rmtree(PYTHON_RUNTIME_DIR)

    PYTHON_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    log(f"解压 Python standalone 到: {PYTHON_RUNTIME_DIR}")
    _extract_prefixed_tarball(archive_path, "python/", PYTHON_RUNTIME_DIR)
    _materialize_python_shims()
    _prune_python_runtime()

    python_bin = _find_extracted_python_binary()
    if not python_bin.exists():
        raise FileNotFoundError(f"解压后缺少 python: {python_bin}")
    log(f"Python standalone 运行时准备完成: {PYTHON_RUNTIME_DIR}")


_RELATIVE_TS_IMPORT_RE = re.compile(r'(?P<quote>["\'])(?P<path>\.{1,2}/[^"\']+?)\.tsx?(?P=quote)')


def _rewrite_openclaw_dist_import_suffixes(dist_root: Path) -> None:
    """将编译产物里残留的相对 .ts/.tsx import 后缀改写为 .js。"""
    changed_files = 0
    changed_refs = 0

    for pattern in ("*.js", "*.mjs", "*.cjs"):
        for candidate in dist_root.rglob(pattern):
            try:
                content = candidate.read_text(encoding="utf-8")
            except Exception:
                continue

            original = content
            rewritten_lines: list[str] = []
            for line in content.splitlines(keepends=True):
                if "import" not in line and "export" not in line:
                    rewritten_lines.append(line)
                    continue
                line, count = _RELATIVE_TS_IMPORT_RE.subn(
                    lambda match: f"{match.group('quote')}{match.group('path')}.js{match.group('quote')}",
                    line,
                )
                changed_refs += count
                rewritten_lines.append(line)

            updated = "".join(rewritten_lines)
            if updated == original:
                continue

            candidate.write_text(updated, encoding="utf-8")
            changed_files += 1

    log(f"OpenClaw dist import 后处理完成: {changed_files} 个文件, {changed_refs} 处引用")


def _sync_openclaw_runtime_sidefiles(vendor_root: Path) -> None:
    """补齐 OpenClaw 运行时中 dist 外的必需文件。"""
    dist_root = OPENCLAW_RUNTIME_DIR / "dist"
    if dist_root.exists():
        _rewrite_openclaw_dist_import_suffixes(dist_root)

    shared_kit_src = vendor_root / "apps" / "shared" / "OpenClawKit"
    if shared_kit_src.exists():
        shared_kit_dst = OPENCLAW_RUNTIME_DIR / "apps" / "shared" / "OpenClawKit"
        shared_kit_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(shared_kit_src, shared_kit_dst, dirs_exist_ok=True)
        log(f"已复制 OpenClawKit 共享资源 -> {shared_kit_dst}")

    gateway_script_src = PROJECT_ROOT / "agentserver" / "openclaw" / "gateway_start.mjs"
    if gateway_script_src.exists():
        shutil.copy2(gateway_script_src, OPENCLAW_RUNTIME_DIR / "gateway_start.mjs")
        log(f"已复制 gateway_start.mjs -> {OPENCLAW_RUNTIME_DIR / 'gateway_start.mjs'}")


def _write_openclaw_tsc_diagnostics(output: str) -> Optional[Path]:
    if not output.strip():
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    diag_path = CACHE_DIR / "openclaw-tsc.log"
    diag_path.write_text(output, encoding="utf-8")
    return diag_path


def _log_openclaw_tsc_excerpt(output: str, limit: int = 20) -> None:
    lines = [line.rstrip() for line in output.splitlines() if line.strip()]
    if not lines:
        return
    for line in lines[:limit]:
        log(f"[openclaw-tsc] {line}")
    remaining = len(lines) - limit
    if remaining > 0:
        log(f"[openclaw-tsc] ... 其余 {remaining} 行已省略")


def preinstall_openclaw(force: bool = False) -> None:
    """编译 vendor/openclaw 源码并复制到运行时目录"""
    vendor_root = PROJECT_ROOT / "vendor" / "openclaw"
    if not vendor_root.exists():
        raise FileNotFoundError(f"vendor/openclaw 不存在: {vendor_root}")

    node_bin = NODE_RUNTIME_DIR / NODE_BIN
    if not node_bin.exists():
        raise FileNotFoundError(f"node 不存在: {node_bin}")

    # 检测是否已有编译产物
    dist_marker = OPENCLAW_RUNTIME_DIR / "dist" / "gateway" / "server.js"
    if not force and dist_marker.exists():
        _sync_openclaw_runtime_sidefiles(vendor_root)
        log("OpenClaw runtime 已存在，跳过编译")
        return

    # 清理旧运行时
    if OPENCLAW_RUNTIME_DIR.exists():
        log(f"清理旧 OpenClaw 运行时: {OPENCLAW_RUNTIME_DIR}")
        shutil.rmtree(OPENCLAW_RUNTIME_DIR)
    OPENCLAW_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    if IS_WINDOWS:
        env["PATH"] = f"{NODE_RUNTIME_DIR}{os.pathsep}{env.get('PATH', '')}"
    else:
        node_bin_dir = NODE_RUNTIME_DIR / "bin"
        env["PATH"] = f"{node_bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env = _apply_runtime_npm_env(env)

    # 1. 安装 vendor 依赖（需要保留平台 postinstall / native 包处理）
    _install_openclaw_vendor_dependencies(vendor_root, env, force=force)

    # 2. 编译 TypeScript
    log("编译 vendor/openclaw 源码...")
    compile_env = env.copy()
    compile_env["NODE_OPTIONS"] = "--max-old-space-size=4096"
    tsc_cli = _find_vendor_typescript_cli(vendor_root)
    log(f"$ {node_bin} {tsc_cli} -p tsconfig.naga.json")
    compile_result = subprocess.run(
        [str(node_bin), str(tsc_cli), "-p", "tsconfig.naga.json"],
        cwd=vendor_root,
        env=compile_env,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    compile_output = "\n".join(part for part in (compile_result.stdout, compile_result.stderr) if part).strip()

    vendor_dist = vendor_root / "dist" / "gateway" / "server.js"
    if compile_result.returncode != 0 and vendor_dist.exists():
        diag_path = _write_openclaw_tsc_diagnostics(compile_output)
        message = (
            f"警告：vendor/openclaw 编译返回非零退出码 {compile_result.returncode}，"
            "但 dist 已生成，继续打包"
        )
        if diag_path:
            message += f"；诊断日志已写入 {diag_path}"
        log(message)
    if not vendor_dist.exists():
        diag_path = _write_openclaw_tsc_diagnostics(compile_output)
        if diag_path:
            log(f"OpenClaw TypeScript 诊断日志: {diag_path}")
        _log_openclaw_tsc_excerpt(compile_output)
        raise FileNotFoundError(f"编译失败：dist/gateway/server.js 不存在: {vendor_dist}")

    # 3. 复制编译产物 + 依赖到 runtime
    log("复制编译产物到运行时目录...")
    shutil.copytree(vendor_root / "dist", OPENCLAW_RUNTIME_DIR / "dist")
    shutil.copytree(vendor_root / "node_modules", OPENCLAW_RUNTIME_DIR / "node_modules")
    shutil.copy2(vendor_root / "package.json", OPENCLAW_RUNTIME_DIR / "package.json")
    shutil.copy2(vendor_root / "openclaw.mjs", OPENCLAW_RUNTIME_DIR / "openclaw.mjs")
    _sync_openclaw_runtime_sidefiles(vendor_root)
    _verify_openclaw_runtime_import(node_bin, env, vendor_root)

    log(f"OpenClaw 运行时准备完成（从源码编译）: {OPENCLAW_RUNTIME_DIR}")


def _agent_browser_bin_name() -> str:
    return "agent-browser.cmd" if IS_WINDOWS else "agent-browser"


def _runtime_node_path_prefix() -> str:
    return str(NODE_RUNTIME_DIR if IS_WINDOWS else NODE_RUNTIME_DIR / "bin")


def _agent_browser_browser_cache_dirs() -> list[Path]:
    return [
        OPENCLAW_RUNTIME_DIR / "node_modules" / "playwright-core" / ".local-browsers",
        OPENCLAW_RUNTIME_DIR / "node_modules" / "agent-browser" / "node_modules" / "playwright-core" / ".local-browsers",
    ]


def _has_agent_browser_browser_cache() -> bool:
    for candidate in _agent_browser_browser_cache_dirs():
        if candidate.exists():
            try:
                if any(candidate.iterdir()):
                    return True
            except Exception:
                return True
    return False


def preinstall_agent_browser(force: bool = False) -> None:
    """在内嵌运行时目录中预装 agent-browser，并预下载浏览器内核"""
    node_bin = NODE_RUNTIME_DIR / NODE_BIN
    if not node_bin.exists():
        raise FileNotFoundError(f"node 不存在: {node_bin}")

    agent_browser_cmd = OPENCLAW_RUNTIME_DIR / "node_modules" / ".bin" / _agent_browser_bin_name()
    agent_browser_pkg = OPENCLAW_RUNTIME_DIR / "node_modules" / "agent-browser" / "package.json"
    playwright_core_cli = OPENCLAW_RUNTIME_DIR / "node_modules" / "playwright-core" / "cli.js"

    installed_version: Optional[str] = None
    if agent_browser_pkg.exists():
        try:
            installed_version = json.loads(agent_browser_pkg.read_text(encoding="utf-8")).get("version")
        except Exception:
            installed_version = None

    if not force and agent_browser_cmd.exists() and _has_agent_browser_browser_cache():
        log(f"agent-browser 已预装: {installed_version or 'unknown'}，跳过安装")
        return
    if agent_browser_cmd.exists() and not _has_agent_browser_browser_cache():
        log("检测到 agent-browser 命令已存在，但浏览器缓存缺失，继续补装 chromium")

    env = os.environ.copy()
    env["PATH"] = f"{_runtime_node_path_prefix()}{os.pathsep}{env.get('PATH', '')}"
    env["NPM_CONFIG_AUDIT"] = "false"
    env["NPM_CONFIG_FUND"] = "false"
    env["NPM_CONFIG_GLOBAL"] = "false"
    env = _apply_runtime_npm_env(env)
    # 将浏览器二进制放进 node_modules，避免首次运行再下载到用户目录。
    env["PLAYWRIGHT_BROWSERS_PATH"] = "0"
    env["CI"] = "1"

    log(f"预装 Agent Browser（npm install {AGENT_BROWSER_NPM_SPEC}）...")
    run(
        _runtime_npm_command(
            "install",
            AGENT_BROWSER_NPM_SPEC,
            "--global=false",
            "--location=project",
            "--prefix",
            str(OPENCLAW_RUNTIME_DIR),
        ),
        cwd=OPENCLAW_RUNTIME_DIR,
        env=env,
    )

    if not agent_browser_cmd.exists():
        raise FileNotFoundError(f"agent-browser 预装失败，未找到命令: {agent_browser_cmd}")
    if not playwright_core_cli.exists():
        raise FileNotFoundError(f"playwright-core cli 缺失，无法预装浏览器内核: {playwright_core_cli}")

    log("预下载 Agent Browser 浏览器依赖（playwright-core install chromium）...")
    run(
        [
            str(node_bin),
            str(playwright_core_cli),
            "install",
            "chromium",
        ],
        cwd=OPENCLAW_RUNTIME_DIR,
        env=env,
    )

    browsers_dirs = [str(path) for path in _agent_browser_browser_cache_dirs() if path.exists()]
    if browsers_dirs:
        log(f"Agent Browser 浏览器缓存已写入: {', '.join(browsers_dirs)}")
    elif not _has_agent_browser_browser_cache():
        raise FileNotFoundError("playwright-core install chromium 执行完成，但未找到浏览器缓存目录")
    log(f"Agent Browser 预装完成: {agent_browser_cmd}")


def download_uv_runtime() -> Path:
    """下载 uv standalone 二进制包，返回本地缓存路径"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = CACHE_DIR / UV_ARCHIVE
    if archive_path.exists():
        log(f"使用缓存 uv 包: {archive_path}")
        return archive_path
    log(f"下载 uv v{UV_VERSION}: {UV_DIST_URL}")
    urllib.request.urlretrieve(UV_DIST_URL, str(archive_path))
    log(f"uv 下载完成: {archive_path} ({archive_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return archive_path


def extract_uv_runtime(archive_path: Path) -> None:
    """解压 uv standalone 到 runtime/uv/"""
    if UV_RUNTIME_DIR.exists():
        # 检查是否已解压
        ext = ".exe" if IS_WINDOWS else ""
        if (UV_RUNTIME_DIR / f"uv{ext}").exists():
            log("uv 运行时已存在，跳过解压")
            return
        shutil.rmtree(UV_RUNTIME_DIR)

    UV_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    log(f"解压 uv 到 {UV_RUNTIME_DIR}")

    if str(archive_path).endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            for member in zf.infolist():
                fname = Path(member.filename).name
                if not fname or member.is_dir():
                    continue
                target = UV_RUNTIME_DIR / fname
                with zf.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    else:
        import tarfile
        with tarfile.open(archive_path) as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                fname = Path(member.name).name
                if not fname:
                    continue
                member.name = fname
                tf.extract(member, UV_RUNTIME_DIR)
                extracted = UV_RUNTIME_DIR / fname
                if not IS_WINDOWS:
                    extracted.chmod(0o755)

    ext = ".exe" if IS_WINDOWS else ""
    if not (UV_RUNTIME_DIR / f"uv{ext}").exists():
        raise FileNotFoundError(f"uv 解压后未找到 uv{ext}")
    log(f"uv 运行时准备完成: {UV_RUNTIME_DIR}")


def prepare_openclaw_runtime(force: bool = False) -> None:
    """准备嵌入式运行时：Node.js + Python standalone + OpenClaw/Agent Browser + uv"""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = download_node_runtime()
    extract_node_runtime(archive_path)
    python_archive = download_python_runtime()
    extract_python_runtime(python_archive)
    preinstall_openclaw(force=force)
    preinstall_agent_browser(force=force)
    # 下载并解压 uv standalone（用于 MCP uvx 服务）
    uv_archive = download_uv_runtime()
    extract_uv_runtime(uv_archive)
    log("嵌入式运行时准备完成（已预装 Node.js + Python + OpenClaw + Agent Browser + uv）")


# ============ Step 4: PyInstaller 编译后端 ============


def build_backend() -> None:
    """用 PyInstaller 编译 Python 后端"""
    if not SPEC_FILE.exists():
        raise FileNotFoundError(f"spec 文件不存在: {SPEC_FILE}")

    work_dir = PROJECT_ROOT / "build" / "pyinstaller"
    work_dir.mkdir(parents=True, exist_ok=True)

    run(
        [
            "uv",
            "run",
            "pyinstaller",
            str(SPEC_FILE),
            "--distpath",
            str(BACKEND_DIST_DIR),
            "--workpath",
            str(work_dir),
            "--clean",
            "-y",
        ],
        cwd=PROJECT_ROOT,
    )

    # 验证产物
    backend_bin = BACKEND_DIST_DIR / "naga-backend" / f"naga-backend{BACKEND_EXT}"
    if not backend_bin.exists():
        raise FileNotFoundError(f"后端编译产物缺失: {backend_bin}")
    log(f"后端编译完成: {backend_bin}")


# ============ Step 5: Electron 前端构建 + 打包 ============


def build_frontend(debug: bool = False) -> None:
    """构建 Vue 前端 + Electron 打包。

    debug=True 时（仅 Windows）会注入 electron-builder metadata，
    让安装后的 Electron 主进程以"调试控制台模式"启动后端。
    """
    # 同步版本号 pyproject.toml → package.json
    sync_frontend_version()

    # 安装前端依赖
    node_modules = FRONTEND_DIR / "node_modules"
    if not node_modules.exists():
        log("安装前端依赖...")
        run(["npm", "install"], cwd=FRONTEND_DIR)

    dist_script = f"dist:{PLATFORM_TAG}"

    if debug and IS_WINDOWS:
        log("调试构建模式：已启用后端日志终端（安装后会弹 cmd 实时输出）")
        run(
            [
                "npm",
                "run",
                dist_script,
                "--",
                "-c.extraMetadata.nagaDebugConsole=true",
            ],
            cwd=FRONTEND_DIR,
        )
    else:
        if debug and not IS_WINDOWS:
            log("注意：--debug 调试控制台仅在 Windows 上生效，已忽略")
        run(["npm", "run", dist_script], cwd=FRONTEND_DIR)

    log("Electron 打包完成")


# ============ Step 6: 汇总 ============


def print_summary() -> None:
    """打印构建产物信息"""
    safe_print()
    safe_print("=" * 50)
    safe_print("  构建完成!")
    safe_print("=" * 50)

    # 后端产物
    backend_dir = BACKEND_DIST_DIR / "naga-backend"
    if backend_dir.exists():
        size = sum(f.stat().st_size for f in backend_dir.rglob("*") if f.is_file())
        log(f"后端产物: {backend_dir}  ({size / 1024 / 1024:.0f} MB)")

    # 运行时（Node.js + OpenClaw + uv）
    runtime_dir = BACKEND_DIST_DIR / "runtime"
    if runtime_dir.exists():
        size = sum(f.stat().st_size for f in runtime_dir.rglob("*") if f.is_file())
        log(f"OpenClaw 运行时: {runtime_dir}  ({size / 1024 / 1024:.0f} MB)")

    # Electron 安装包
    release_dir = FRONTEND_DIR / "release"
    if release_dir.exists():
        for f in release_dir.glob(INSTALLER_GLOB):
            log(f"安装包: {f}  ({f.stat().st_size / 1024 / 1024:.0f} MB)")


# ============ 主入口 ============


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NagaAgent 跨平台构建脚本")
    parser.add_argument(
        "--skip-openclaw",
        action="store_true",
        help="跳过 OpenClaw 运行时准备（Node 便携版 + OpenClaw 预装）",
    )
    parser.add_argument("--backend-only", action="store_true", help="仅编译后端，不打包 Electron")
    parser.add_argument(
        "--force-openclaw",
        action="store_true",
        help="强制重新安装 OpenClaw（先删除旧安装）",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="调试打包：安装后启动时弹出后端日志终端（仅 Windows 生效）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start_time = time.time()

    # 计算总步骤数
    total_steps = 2  # 环境检查 + 同步依赖
    if not args.skip_openclaw:
        total_steps += 1
    total_steps += 1  # 编译后端
    if not args.backend_only:
        total_steps += 1  # 前端打包

    step = 0

    # Step 1: 环境检查
    step += 1
    log_step(step, total_steps, "环境检查")
    if not check_environment():
        log("环境检查未通过，请先安装缺失的工具")
        sys.exit(1)

    # Step 2: 同步依赖
    step += 1
    log_step(step, total_steps, "同步 Python 依赖")
    sync_dependencies()

    # Step 3: OpenClaw 运行时
    if not args.skip_openclaw:
        step += 1
        log_step(step, total_steps, "准备 OpenClaw 运行时（含预装）")
        prepare_openclaw_runtime(force=args.force_openclaw)

    # Step 4: 编译后端
    step += 1
    log_step(step, total_steps, "PyInstaller 编译后端")
    build_backend()

    # Step 5: 前端打包
    if not args.backend_only:
        step += 1
        title = "Electron 前端打包（DEBUG）" if args.debug else "Electron 前端打包"
        log_step(step, total_steps, title)
        build_frontend(debug=args.debug)

    # 汇总
    print_summary()
    elapsed = time.time() - start_time
    log(f"总耗时: {elapsed / 60:.1f} 分钟")


if __name__ == "__main__":
    main()
