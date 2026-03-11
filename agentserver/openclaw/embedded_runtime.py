#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenClaw 内嵌运行时管理

统一机制：vendor/openclaw 源码 → node 直接启动。
- 开发模式：npm install 安装依赖 → tsx 直接跑 TypeScript 源码（零编译）
- 打包模式：CI 预编译 dist → node 跑编译产物
"""

import os
import sys
import shutil
import asyncio
import logging
import platform
import socket
import subprocess
from pathlib import Path
from typing import Optional, Dict, List

logger = logging.getLogger("openclaw.runtime")

# 是否为 PyInstaller 打包环境
IS_PACKAGED: bool = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


class EmbeddedRuntime:
    """
    内嵌运行时管理器

    打包环境：从 resources/openclaw-runtime/ 加载 Node.js + 预编译 dist
    开发环境：vendor/openclaw/ 源码 + tsx 直接执行
    """

    def __init__(self) -> None:
        self._gateway_process: Optional[asyncio.subprocess.Process] = None
        self._runtime_root: Optional[Path] = None
        self._onboarded: bool = False

        if IS_PACKAGED:
            self._runtime_root = self._resolve_runtime_root()
            if self._runtime_root and self._runtime_root.exists():
                logger.info(f"内嵌运行时目录: {self._runtime_root}")
            else:
                logger.warning(f"内嵌运行时目录不存在: {self._runtime_root}")
                self._runtime_root = None

    # ============ 路径推导 ============

    @staticmethod
    def _resolve_runtime_root() -> Path:
        """
        推导内嵌运行时根目录。

        打包后目录结构：
          resources/
            backend/
              naga-backend.exe
              _internal/          <- sys._MEIPASS
            openclaw-runtime/
              node/
              openclaw/
        """
        meipass = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        # _internal -> backend -> resources -> openclaw-runtime
        return meipass.parent.parent / "openclaw-runtime"

    @property
    def is_packaged(self) -> bool:
        return IS_PACKAGED and self._runtime_root is not None

    @property
    def runtime_root(self) -> Optional[Path]:
        return self._runtime_root

    # ============ Vendor 路径 ============

    def _get_vendor_root(self) -> Path:
        """获取 vendor/openclaw 目录。

        打包模式：runtime/openclaw/（内含预编译 dist + node_modules）
        开发模式：项目根 vendor/openclaw/（源码 + 共享 node_modules）
        """
        if self.is_packaged and self._runtime_root:
            return self._runtime_root / "openclaw"
        return Path(__file__).resolve().parent.parent.parent / "vendor" / "openclaw"

    @property
    def vendor_root(self) -> Path:
        return self._get_vendor_root()

    def _has_compiled_dist(self) -> bool:
        """是否有编译好的 dist"""
        return (self._get_vendor_root() / "dist" / "gateway" / "server.js").exists()

    def _has_ts_source(self) -> bool:
        """是否有 TypeScript 源码"""
        return (self._get_vendor_root() / "src" / "gateway" / "server.ts").exists()

    def _has_tsx(self) -> bool:
        """tsx 是否可用（开发模式 devDependency）"""
        return (self._get_vendor_root() / "node_modules" / "tsx").exists()

    @property
    def is_vendor_ready(self) -> bool:
        """vendor 是否可以启动 Gateway。

        满足以下任一条件即可：
        1. 有编译好的 dist（打包模式 / 手动 tsc 后）
        2. 有 TS 源码 + tsx 可用（开发模式，npm install 后）
        """
        if self._has_compiled_dist():
            return True
        if self._has_ts_source() and self._has_tsx():
            return True
        return False

    @property
    def runtime_mode(self) -> str:
        """返回当前运行时模式描述"""
        if self.is_packaged:
            return "packaged"
        if self._has_compiled_dist():
            return "vendor-compiled"
        if self._has_ts_source() and self._has_tsx():
            return "vendor-source"
        if self._has_ts_source():
            return "vendor-needs-deps"
        return "unavailable"

    # ============ 可执行文件路径 ============

    def _platform_bin(self, subdir: str, name: str) -> Optional[str]:
        """在 runtime_root/<subdir>/ 下查找可执行文件（自动处理平台差异）"""
        assert self._runtime_root is not None
        is_win = platform.system() == "Windows"
        if is_win:
            for ext in (".cmd", ".exe", ""):
                p = self._runtime_root / subdir / f"{name}{ext}"
                if p.exists():
                    return str(p)
        else:
            for prefix in ("bin/", ""):
                p = self._runtime_root / subdir / f"{prefix}{name}"
                if p.exists():
                    return str(p)
        return None

    @property
    def node_path(self) -> Optional[str]:
        """Node.js 可执行文件路径"""
        if self.is_packaged:
            return self._platform_bin("node", "node")
        return shutil.which("node")

    @property
    def npm_path(self) -> Optional[str]:
        """npm 可执行文件路径"""
        if self.is_packaged:
            return self._platform_bin("node", "npm")
        return shutil.which("npm")

    @property
    def npx_path(self) -> Optional[str]:
        """npx 可执行文件路径"""
        if self.is_packaged:
            return self._platform_bin("node", "npx")
        return shutil.which("npx")

    @property
    def uv_path(self) -> Optional[str]:
        """uv 可执行文件路径"""
        if self.is_packaged:
            return self._platform_bin("uv", "uv")
        return shutil.which("uv")

    @property
    def uvx_path(self) -> Optional[str]:
        """uvx 可执行文件路径"""
        if self.is_packaged:
            return self._platform_bin("uv", "uvx")
        return shutil.which("uvx")

    @property
    def openclaw_path(self) -> Optional[str]:
        """openclaw CLI 入口（vendor/openclaw/openclaw.mjs）"""
        vendor = self._get_vendor_root()
        mjs = vendor / "openclaw.mjs"
        if mjs.exists() and self.node_path:
            return str(mjs)
        return None

    @property
    def clawhub_path(self) -> Optional[str]:
        """clawhub CLI（不再支持全局安装）"""
        return None

    # ============ 统一命令解析 ============

    def resolve_command(self, cmd: str) -> Optional[str]:
        """将命令名解析为内置路径或系统 PATH"""
        mapping: Dict[str, Optional[str]] = {
            "node": self.node_path,
            "npm": self.npm_path,
            "npx": self.npx_path,
            "uv": self.uv_path,
            "uvx": self.uvx_path,
            "openclaw": self.openclaw_path,
            "clawhub": self.clawhub_path,
        }
        resolved = mapping.get(cmd)
        if resolved:
            return resolved
        return shutil.which(cmd)

    # ============ 环境变量 ============

    @property
    def env(self) -> Dict[str, str]:
        """构建子进程环境变量，确保内嵌 node / uv 优先"""
        env = os.environ.copy()

        # 确保 localhost 通信不走代理（外部 LLM API 仍然走梯子）
        no_proxy = env.get("NO_PROXY", env.get("no_proxy", ""))
        local_hosts = "localhost,127.0.0.1,0.0.0.0"
        if local_hosts not in no_proxy:
            env["NO_PROXY"] = f"{local_hosts},{no_proxy}" if no_proxy else local_hosts
            env["no_proxy"] = env["NO_PROXY"]

        extra_dirs: list[str] = []

        if self.is_packaged and self._runtime_root is not None:
            node_dir = self._runtime_root / "node"
            if node_dir.exists():
                extra_dirs.append(str(node_dir))
            uv_dir = self._runtime_root / "uv"
            if uv_dir.exists():
                extra_dirs.append(str(uv_dir))
            env["PLAYWRIGHT_BROWSERS_PATH"] = "0"

        # vendor node_modules/.bin 始终加入（开发 + 打包都需要）
        vendor_bin = self._get_vendor_root() / "node_modules" / ".bin"
        if vendor_bin.exists():
            extra_dirs.append(str(vendor_bin))

        if extra_dirs:
            env["PATH"] = os.pathsep.join(extra_dirs) + os.pathsep + env.get("PATH", "")
        return env

    # ============ Node.js 版本检测 ============

    def get_node_version(self) -> tuple[bool, Optional[str]]:
        """获取 Node.js 版本并检查是否满足要求 (>=22)"""
        node = self.node_path
        if not node:
            return False, None
        try:
            result = subprocess.run(
                [node, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                env=self.env,
            )
            if result.returncode == 0:
                version_str = result.stdout.strip().lstrip("v")
                major = int(version_str.split(".")[0])
                return major >= 22, version_str
        except Exception as e:
            logger.warning(f"检查 Node.js 版本失败: {e}")
        return False, None

    # ============ Vendor 依赖安装 ============

    def _find_npm_cli(self) -> Optional[Path]:
        """定位 npm-cli.js（绕过 npm.cmd，避免 asyncio 兼容问题）"""
        if self.is_packaged and self._runtime_root:
            for candidate in [
                self._runtime_root / "node" / "node_modules" / "npm" / "bin" / "npm-cli.js",
                self._runtime_root / "node" / "node_modules" / "npm" / "bin" / "npm-cli.mjs",
                self._runtime_root / "node" / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js",
            ]:
                if candidate.exists():
                    return candidate
        return None

    async def ensure_vendor_ready(self) -> bool:
        """确保 vendor 可以启动 Gateway。

        开发模式下仅安装依赖（npm install），tsx 直接跑源码，无需编译。
        打包模式下 dist 应由 CI 预编译，这里只做检查。
        """
        if self.is_vendor_ready:
            return True

        vendor_root = self._get_vendor_root()

        if self.is_packaged:
            logger.error(f"打包模式下 vendor dist 缺失: {vendor_root / 'dist'}")
            return False

        if not (vendor_root / "package.json").exists():
            logger.error(f"vendor/openclaw 目录不存在: {vendor_root}")
            return False

        node = self.node_path
        if not node:
            logger.error("Node.js 不可用，无法安装 vendor/openclaw 依赖")
            return False

        # 安装依赖（包含 tsx 等 devDependencies）
        if not (vendor_root / "node_modules").exists():
            logger.info("首次启动：安装 vendor/openclaw 依赖...")

            # 构建 npm 命令（绕过 .cmd）
            npm_cli = self._find_npm_cli()
            if npm_cli:
                npm_cmd = [node, str(npm_cli)]
            else:
                npm = self.npm_path
                if not npm:
                    logger.error("npm 不可用，无法安装依赖")
                    return False
                npm_cmd = [npm]

            try:
                proc = await asyncio.create_subprocess_exec(
                    *npm_cmd,
                    "install",
                    "--ignore-scripts",
                    cwd=str(vendor_root),
                    env=self.env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

                if proc.returncode != 0:
                    err = stderr.decode(errors="ignore")[:500] if stderr else ""
                    logger.warning(f"npm install --ignore-scripts 失败（尝试不带 --ignore-scripts）: {err}")
                    # 兜底：不带 --ignore-scripts 重试
                    proc = await asyncio.create_subprocess_exec(
                        *npm_cmd,
                        "install",
                        cwd=str(vendor_root),
                        env=self.env,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
                    if proc.returncode != 0:
                        err = stderr.decode(errors="ignore")[:500] if stderr else ""
                        logger.error(f"npm install 失败: {err}")
                        return False

                logger.info("vendor/openclaw 依赖安装完成")
            except asyncio.TimeoutError:
                logger.error("npm install 超时（300秒）")
                return False
            except Exception as e:
                logger.error(f"npm install 执行异常: {e}")
                return False

        return self.is_vendor_ready

    # ============ Gateway 进程管理 ============

    def _build_gateway_cmd(self) -> Optional[List[str]]:
        """构建启动 Gateway 的命令列表。

        打包模式：node gateway_start.mjs（搜索预编译 dist）
        开发模式（有 dist）：node gateway_start.mjs
        开发模式（无 dist）：node --import tsx gateway_start.mjs（tsx 跑 TS 源码）
        """
        node = self.node_path
        if not node:
            return None

        # gateway_start.mjs 位置
        if self.is_packaged and self._runtime_root:
            entry = self._runtime_root / "openclaw" / "gateway_start.mjs"
        else:
            entry = Path(__file__).parent / "gateway_start.mjs"
        if not entry.exists():
            logger.error(f"gateway_start.mjs 不存在: {entry}")
            return None

        # 开发模式且无编译产物 → 用 tsx 跑源码
        if not self.is_packaged and not self._has_compiled_dist() and self._has_tsx():
            return [node, "--import", "tsx", str(entry)]
        return [node, str(entry)]

    def _get_gateway_cwd(self) -> Optional[str]:
        """Gateway 子进程的工作目录。

        tsx 需要能从 cwd 解析 node_modules，所以 dev 源码模式下设为 vendor root。
        """
        if not self.is_packaged and not self._has_compiled_dist() and self._has_tsx():
            return str(self._get_vendor_root())
        return None

    def _pipe_gateway_logs(self, proc: asyncio.subprocess.Process):
        """后台任务：持续读取 Gateway 进程的 stdout/stderr 并转发到 Python logger"""
        async def _reader(stream, level):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode(errors="ignore").rstrip()
                if text:
                    logger.log(level, f"[Gateway] {text}")

        if proc.stdout:
            asyncio.ensure_future(_reader(proc.stdout, logging.INFO))
        if proc.stderr:
            asyncio.ensure_future(_reader(proc.stderr, logging.WARNING))

    async def start_gateway(self) -> bool:
        """启动 OpenClaw Gateway 进程"""
        # 进程已存在且仍在运行 → 跳过
        if self._gateway_process is not None and self._gateway_process.returncode is None:
            logger.info("Gateway 进程已在运行")
            return True
        # 进程已退出 → 清理引用以便重新启动
        if self._gateway_process is not None:
            logger.warning(f"Gateway 进程已退出 (code={self._gateway_process.returncode})，清理后重新启动")
            self._gateway_process = None

        cmd = self._build_gateway_cmd()
        if not cmd:
            logger.error("无法构建 Gateway 启动命令")
            return False

        try:
            logger.info(f"启动 OpenClaw Gateway: {' '.join(cmd)}")
            port = self._get_gateway_port()

            gw_env = self.env
            gw_env["OPENCLAW_GATEWAY_PORT"] = str(port)
            try:
                from system.config import config as _cfg
                search_base = getattr(_cfg.online_search, "search_api_base", "")
                if search_base:
                    gw_env["BRAVE_SEARCH_BASE_URL"] = search_base
            except Exception:
                pass

            cwd = self._get_gateway_cwd()
            self._gateway_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=gw_env,
                cwd=cwd,
            )

            # 后台转发 Gateway 日志
            self._pipe_gateway_logs(self._gateway_process)

            # 轮询等待 Gateway 就绪
            ready = False
            for _attempt in range(15):
                await asyncio.sleep(1)
                if self._gateway_process.returncode is not None:
                    break
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1)
                    if sock.connect_ex(("127.0.0.1", port)) == 0:
                        ready = True
                        sock.close()
                        break
                    sock.close()
                except Exception:
                    pass

            if self._gateway_process.returncode is not None:
                stderr_data = await self._gateway_process.stderr.read() if self._gateway_process.stderr else b""
                logger.error(
                    f"Gateway 进程异常退出 (code={self._gateway_process.returncode}): "
                    f"{stderr_data.decode(errors='ignore')[:500]}"
                )
                self._gateway_process = None
                return False

            if ready:
                logger.info("OpenClaw Gateway 已启动（端口就绪）")
            else:
                logger.warning("Gateway 进程运行中但端口未就绪，继续运行...")
            return self._gateway_process is not None and self._gateway_process.returncode is None
        except Exception as e:
            logger.error(f"启动 Gateway 失败: {e}")
            self._gateway_process = None
            return False

    async def start_gateway_on_port(self, port: int) -> Optional[asyncio.subprocess.Process]:
        """在指定端口启动一个独立 Gateway 进程（供 InstanceManager 调用，不影响主实例）。"""
        cmd = self._build_gateway_cmd()
        if not cmd:
            logger.error(f"[port={port}] 无法构建 Gateway 启动命令（node 不可用或 gateway_start.mjs 缺失）")
            return None

        gw_env = self.env.copy()
        gw_env["OPENCLAW_GATEWAY_PORT"] = str(port)
        try:
            from system.config import config as _cfg
            search_base = getattr(_cfg.online_search, "search_api_base", "")
            if search_base:
                gw_env["BRAVE_SEARCH_BASE_URL"] = search_base
        except Exception:
            pass

        cwd = self._get_gateway_cwd()
        try:
            logger.info(f"[port={port}] 启动 Gateway 子实例: {' '.join(cmd)}")
            logger.info(f"[port={port}] cwd={cwd}, OPENCLAW_GATEWAY_PORT={port}")
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=gw_env,
                cwd=cwd,
            )
            logger.info(f"[port={port}] 进程已创建 pid={process.pid}")
            self._pipe_gateway_logs(process)

            for attempt in range(15):
                await asyncio.sleep(1)
                if process.returncode is not None:
                    stdout_data = await process.stdout.read() if process.stdout else b""
                    stderr_data = await process.stderr.read() if process.stderr else b""
                    logger.error(
                        f"[port={port}] Gateway 子实例异常退出 (code={process.returncode})\n"
                        f"  stdout: {stdout_data.decode(errors='ignore')[:500]}\n"
                        f"  stderr: {stderr_data.decode(errors='ignore')[:500]}"
                    )
                    return None
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1)
                    if sock.connect_ex(("127.0.0.1", port)) == 0:
                        sock.close()
                        logger.info(f"[port={port}] Gateway 子实例已就绪 (等待 {attempt+1}s)")
                        return process
                    sock.close()
                except Exception:
                    pass
                if attempt == 4 or attempt == 9:
                    logger.info(f"[port={port}] 等待端口就绪... ({attempt+1}/15)")

            # 15s 后仍未就绪
            logger.warning(f"[port={port}] 进程运行中(pid={process.pid})但端口 15s 内未就绪")
            return process
        except Exception as e:
            logger.error(f"[port={port}] 启动 Gateway 子实例失败: {e}", exc_info=True)
            return None

    async def stop_gateway(self) -> None:
        """停止内嵌 Gateway 进程"""
        if self._gateway_process is None:
            return
        try:
            logger.info("正在停止 OpenClaw Gateway...")
            self._gateway_process.terminate()
            try:
                await asyncio.wait_for(self._gateway_process.wait(), timeout=10)
            except asyncio.TimeoutError:
                logger.warning("Gateway 进程未在 10 秒内退出，强制终止")
                self._gateway_process.kill()
                await self._gateway_process.wait()
            logger.info("OpenClaw Gateway 已停止")
        except Exception as e:
            logger.error(f"停止 Gateway 失败: {e}")
        finally:
            self._gateway_process = None

    @property
    def gateway_running(self) -> bool:
        """Gateway 进程是否在运行"""
        return self._gateway_process is not None and self._gateway_process.returncode is None

    @staticmethod
    def _get_gateway_port() -> int:
        """从 system.config 读取 Gateway 端口"""
        try:
            from system.config import config as _cfg
            return _cfg.openclaw.gateway_port
        except Exception:
            return 20789

    def is_gateway_port_in_use(self, host: str = "127.0.0.1", port: int = None) -> bool:
        """检测 Gateway 端口是否被占用"""
        if port is None:
            port = self._get_gateway_port()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                return sock.connect_ex((host, port)) == 0
        except Exception:
            return False

    def has_gateway_process(self) -> bool:
        """检测系统中是否存在 OpenClaw Gateway 相关进程"""
        try:
            import psutil
        except Exception as e:
            logger.debug(f"psutil 不可用，跳过 Gateway 进程检测: {e}")
            return False

        current_pid: int = os.getpid()
        for proc in psutil.process_iter(attrs=["pid", "name", "cmdline"]):
            try:
                pid: int = int(proc.info.get("pid") or 0)
                if pid == current_pid:
                    continue
                name: str = str(proc.info.get("name") or "").lower()
                raw_cmdline = proc.info.get("cmdline") or []
                if isinstance(raw_cmdline, list):
                    cmdline_text = " ".join(str(item) for item in raw_cmdline).lower()
                else:
                    cmdline_text = str(raw_cmdline).lower()
                if "openclaw" in cmdline_text and "gateway" in cmdline_text:
                    return True
                if name.startswith("node") and "openclaw" in cmdline_text and "gateway" in cmdline_text:
                    return True
            except Exception:
                continue
        return False

    async def _stop_gateway_via_cli(self, max_retries: int = 3, retry_interval_seconds: float = 1.0) -> bool:
        """通过 openclaw CLI 停止 Gateway（兜底）"""
        node = self.node_path
        vendor = self._get_vendor_root()
        openclaw_mjs = vendor / "openclaw.mjs"

        if not node or not openclaw_mjs.exists():
            logger.warning("vendor/openclaw/openclaw.mjs 不可用，无法执行 gateway stop")
            return False
        cmd = [node, str(openclaw_mjs)]

        attempts = max(1, max_retries)
        for attempt in range(1, attempts + 1):
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd, "gateway", "stop",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=self.env,
                )
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
                if process.returncode == 0:
                    logger.info(f"已通过 openclaw gateway stop 停止 Gateway（第 {attempt} 次）")
                    return True
                err_text = stderr.decode(errors="ignore")[:200] if stderr else ""
                logger.warning(f"openclaw gateway stop 返回非0({process.returncode})，第 {attempt}/{attempts} 次: {err_text}")
            except asyncio.TimeoutError:
                logger.warning(f"openclaw gateway stop 超时（第 {attempt}/{attempts} 次）")
            except Exception as e:
                logger.warning(f"openclaw gateway stop 失败（第 {attempt}/{attempts} 次）: {e}")
            if attempt < attempts:
                await asyncio.sleep(max(0.0, retry_interval_seconds))
        return False

    # ============ Onboard 初始化 ============

    def _generate_fallback_config(self) -> bool:
        """onboard 失败时的兜底：直接生成 ~/.openclaw/openclaw.json"""
        import json

        config_dir = Path.home() / ".openclaw"
        config_file = config_dir / "openclaw.json"
        workspace_dir = config_dir / "workspace"

        try:
            config_dir.mkdir(parents=True, exist_ok=True)
            workspace_dir.mkdir(parents=True, exist_ok=True)
            from .installer import OpenClawInstaller
            openclaw_config = OpenClawInstaller.build_config_from_naga()
            config_file.write_text(
                json.dumps(openclaw_config, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info(f"Fallback 配置已生成: {config_file}")
            return True
        except Exception as e:
            logger.error(f"生成 fallback 配置失败: {e}")
            return False

    async def ensure_onboarded(self) -> bool:
        """确保 OpenClaw 已完成初始化配置（统一逻辑，不区分打包/开发）"""
        config_file = Path.home() / ".openclaw" / "openclaw.json"

        if config_file.exists():
            # 已有配置，执行兼容补丁
            try:
                from .llm_config_bridge import (
                    ensure_hooks_allow_request_session_key,
                    ensure_gateway_local_mode,
                    ensure_hooks_path,
                )
                ensure_hooks_allow_request_session_key(auto_create=False)
                ensure_gateway_local_mode(auto_create=False)
                ensure_hooks_path(auto_create=False)
            except Exception as e:
                logger.warning(f"配置兼容补丁执行失败（可忽略）: {e}")
            self._onboarded = True
            return True

        # 配置不存在 → 自动生成
        from .llm_config_bridge import (
            ensure_openclaw_config,
            inject_naga_llm_config,
            ensure_hooks_allow_request_session_key,
            ensure_gateway_local_mode,
        )

        try:
            ensure_openclaw_config()
            inject_naga_llm_config()
            ensure_hooks_allow_request_session_key(auto_create=False)
            ensure_gateway_local_mode(auto_create=False)
            self._onboarded = True
            logger.info("已自动生成 OpenClaw 配置")
            return True
        except Exception as e:
            logger.error(f"自动生成配置失败: {e}")

        # 兜底
        if not config_file.exists():
            logger.warning("使用 fallback 直接生成配置...")
            if self._generate_fallback_config():
                self._onboarded = True
                return True
        return False


# ============ 全局单例 ============

_runtime: Optional[EmbeddedRuntime] = None


def get_embedded_runtime() -> EmbeddedRuntime:
    """获取全局 EmbeddedRuntime 单例"""
    global _runtime
    if _runtime is None:
        _runtime = EmbeddedRuntime()
    return _runtime
