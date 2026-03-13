#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenClaw 多实例管理器 — 通讯录模式

每个干员（Agent）有独立目录 ~/.naga/agents/{name}/，包含 workspace 文件。
进程生命周期与通讯录绑定：
  - 创建角色 → 写 manifest + 创建目录（不启动进程）
  - 发消息时 → ensure_running() 按需启动进程
  - 关闭 tab → 进程继续运行
  - 删除角色 → 杀进程 + 可选删数据
  - 关闭 Naga → 杀所有进程

端口映射：
  第一个启动的干员 → 20789（主 Gateway，由 EmbeddedRuntime 管理）
  后续干员 → 20790+（新进程）
"""

import asyncio
import json
import logging
import os
import shutil
import signal
import socket
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .embedded_runtime import EmbeddedRuntime
from .openclaw_client import OpenClawClient, OpenClawConfig

logger = logging.getLogger("openclaw.instance_manager")

MAX_INSTANCES = 100
PORT_RANGE_START = 20789
PORT_RANGE_END = 20889  # exclusive

# ── 通讯录目录 ──

_AGENTS_DIR: Optional[Path] = None


def _get_agents_dir() -> Path:
    global _AGENTS_DIR
    if _AGENTS_DIR is None:
        try:
            from system.config import get_data_dir
            _AGENTS_DIR = get_data_dir() / "agents"
        except Exception:
            _AGENTS_DIR = Path.home() / ".naga" / "agents"
    _AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    return _AGENTS_DIR


def _get_manifest_path() -> Path:
    return _get_agents_dir() / "agents.json"


def _load_manifest() -> dict:
    path = _get_manifest_path()
    if not path.exists():
        return {"agents": [], "next_agent_number": 0}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"agents": [], "next_agent_number": 0}


def _save_manifest(data: dict):
    path = _get_manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data["last_updated"] = datetime.now().isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Workspace 文件初始化 ──

_OPENCLAW_WORKSPACE_FILES = {
    "HEARTBEAT.md": "",
    "IDENTITY.md": "",
    "SOUL.md": "",
    "TOOLS.md": (
        "# 干员工具补充\n\n"
        "## 跨干员协作\n\n"
        "- 查看干员通讯录：`GET http://127.0.0.1:8000/agents/directory`\n"
        "- 转发任务给另一名干员：`POST http://127.0.0.1:8000/agents/relay`\n"
        "- 推荐请求体字段：`target_agent_id` 或 `target_agent_name`、`message`、`purpose`、`context`\n"
        "- 若要调用本地 HTTP 接口，优先使用你现有的命令执行能力发起请求，不要伪造协作结果。\n"
    ),
    "USER.md": "",
}

_COMMON_AGENT_DIRS = ("memory", "skills", "notes")
_COMMON_AGENT_FILES = {
    "IDENTITY.md": "",
    "SOUL.md": "",
    "notes/CLAUDE.md": (
        "# 干员记事本\n\n"
        "这里用于存放该干员的长期约束、长期计划、固定注意事项和手工补充资料。\n"
    ),
}

SUPPORTED_AGENT_ENGINES = {"openclaw", "naga-core"}


def normalize_agent_engine(engine: Optional[str]) -> str:
    value = (engine or "openclaw").strip().lower()
    if value in {"nagacore", "naga_core"}:
        value = "naga-core"
    if value not in SUPPORTED_AGENT_ENGINES:
        raise ValueError(f"不支持的干员引擎: {engine}")
    return value


def _load_character_identity_content(character_template: Optional[str]) -> str:
    if not character_template:
        return ""

    try:
        from system.character_bundle import build_character_identity_bundle

        return build_character_identity_bundle(character_template)
    except Exception as e:
        logger.warning(f"加载角色模板 [{character_template}] 失败: {e}")
        return ""


def get_agent_dir(agent_id: str) -> Path:
    return _get_agents_dir() / agent_id


def _init_agent_dir(
    agent_id: str,
    agent_name: str = "",
    character_template: Optional[str] = None,
    engine: str = "openclaw",
) -> Path:
    """创建干员目录（以 UUID 命名）并初始化 workspace 文件。返回目录路径。"""
    engine = normalize_agent_engine(engine)
    agent_dir = get_agent_dir(agent_id)
    agent_dir.mkdir(parents=True, exist_ok=True)

    for relative_dir in _COMMON_AGENT_DIRS:
        (agent_dir / relative_dir).mkdir(parents=True, exist_ok=True)

    if engine == "openclaw":
        # AGENTS.md 单独处理：包含干员名称
        agents_md = agent_dir / "AGENTS.md"
        if not agents_md.exists():
            display_name = agent_name or agent_id[:8]
            agents_md.write_text(
                f"# {display_name}\n\n"
                f"你是 NagaAgent 系统的干员「{display_name}」。\n"
                f"你可以独立完成用户分配的任务，使用可用的工具和技能。\n"
                f"将重要信息记录到 memory/ 目录中的日期文件，以便跨会话保持记忆。\n",
                encoding="utf-8",
            )

    identity_content = _load_character_identity_content(character_template)

    common_files = dict(_COMMON_AGENT_FILES)
    if engine == "openclaw":
        common_files.update(_OPENCLAW_WORKSPACE_FILES)

    for filename, default_content in common_files.items():
        fp = agent_dir / filename
        fp.parent.mkdir(parents=True, exist_ok=True)
        if not fp.exists():
            content = identity_content if filename == "IDENTITY.md" and identity_content else default_content
            fp.write_text(content, encoding="utf-8")
        elif filename == "IDENTITY.md" and identity_content and character_template:
            try:
                from system.character_bundle import is_legacy_character_identity

                current_text = fp.read_text(encoding="utf-8")
                if is_legacy_character_identity(current_text, character_template):
                    fp.write_text(identity_content, encoding="utf-8")
            except Exception:
                pass
        elif filename == "TOOLS.md" and default_content:
            try:
                if not fp.read_text(encoding="utf-8").strip():
                    fp.write_text(default_content, encoding="utf-8")
            except Exception:
                pass
    return agent_dir


def _delete_agent_dir(agent_id: str) -> bool:
    """删除干员目录（含所有 workspace 文件）。"""
    agent_dir = _get_agents_dir() / agent_id
    if agent_dir.exists():
        shutil.rmtree(agent_dir, ignore_errors=True)
        return True
    return False


@dataclass
class AgentInstance:
    """一个干员实例（通讯录条目 + 可选的运行时状态）"""

    id: str
    name: str
    port: int = 0  # 0 = 未分配（未启动）
    process: Optional[asyncio.subprocess.Process] = None
    client: Optional[OpenClawClient] = None
    primary: bool = False
    running: bool = False
    created_at: float = field(default_factory=time.time)
    character_template: Optional[str] = None
    engine: str = "openclaw"


def cleanup_port_range(start: int = PORT_RANGE_START, end: int = PORT_RANGE_END) -> int:
    """启动时清理端口范围内的残留进程。返回清理的数量。"""
    killed = 0
    for port in range(start, end):
        killed += _kill_stale_on_port(port)
    if killed:
        logger.info(f"端口清理完成，共清理 {killed} 个残留进程")
    return killed


def _kill_stale_on_port(port: int) -> int:
    """杀掉占用指定端口的 openclaw/gateway 残留进程（跨平台）。"""
    import subprocess as _sp

    killed = 0
    try:
        result = _sp.run(
            ["lsof", "-ti", f"tcp:{port}"],
            capture_output=True, text=True, timeout=5,
        )
        pids = [int(p) for p in result.stdout.strip().split() if p.isdigit()]
    except Exception:
        return 0

    for pid in pids:
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info(f"清理残留进程 port={port} pid={pid}")
            killed += 1
        except (ProcessLookupError, PermissionError):
            pass
    return killed


class InstanceManager:
    """
    管理干员通讯录 + 进程生命周期。

    通讯录条目持久化在 manifest 中，进程按需启动。
    第一个启动的干员复用主 Gateway（20789），后续启动独立 Gateway。
    """

    def __init__(self, runtime: EmbeddedRuntime, primary_client: Optional[OpenClawClient] = None) -> None:
        self._runtime = runtime
        self._primary_client = primary_client
        self._instances: Dict[str, AgentInstance] = {}
        self._port_pool: List[int] = []
        self._base_port: int = 20790
        self._next_port: int = self._base_port
        self._agent_counter: int = 0

    def _allocate_port(self) -> int:
        if self._port_pool:
            return self._port_pool.pop(0)
        port = self._next_port
        self._next_port += 1
        return port

    def _release_port(self, port: int) -> None:
        if port > 0 and port not in self._port_pool:
            self._port_pool.append(port)

    def _get_tokens(self):
        try:
            from .detector import get_openclaw_token, get_openclaw_hooks_token
            return get_openclaw_token(), get_openclaw_hooks_token()
        except Exception:
            return None, None

    def _get_primary_port(self) -> int:
        try:
            from system.config import config as _cfg
            return _cfg.openclaw.gateway_port
        except Exception:
            return 20789

    # ── 通讯录操作（不启动进程） ──

    def create_agent(
        self,
        name: Optional[str] = None,
        agent_id: Optional[str] = None,
        character_template: Optional[str] = None,
        engine: str = "openclaw",
    ) -> AgentInstance:
        """创建干员（写 manifest + 创建目录），不启动进程。"""
        if len(self._instances) >= MAX_INSTANCES:
            raise RuntimeError("干员数量最多100个，如有特殊需求请联系开发组")

        engine = normalize_agent_engine(engine)

        self._agent_counter += 1
        if not name:
            name = f"干员{self._agent_counter}"

        if agent_id is None:
            agent_id = uuid.uuid4().hex[:12]

        # 创建目录 + workspace 文件（用 UUID 命名，含干员名称）
        _init_agent_dir(agent_id, name, character_template, engine=engine)

        inst = AgentInstance(
            id=agent_id,
            name=name,
            created_at=time.time(),
            character_template=character_template,
            engine=engine,
        )
        self._instances[agent_id] = inst
        self._save_to_manifest()

        logger.info(f"创建干员 [{name}] id={agent_id} engine={engine}（通讯录条目，未启动进程）")
        return inst

    def delete_agent(self, agent_id: str, delete_data: bool = True) -> None:
        """从通讯录删除干员 + 停止进程 + 可选删数据。"""
        inst = self._instances.pop(agent_id, None)
        if inst is None:
            logger.warning(f"干员 {agent_id} 不存在")
            return

        logger.info(f"删除干员 [{inst.name}] id={agent_id} delete_data={delete_data}")

        # 同步方式标记需要清理，实际清理在 async 方法中执行
        # 这里只做 manifest 和目录清理
        if delete_data:
            _delete_agent_dir(inst.id)
            # 清理 session 文件
            try:
                sf = Path.home() / "NagaAgent" / f"openclaw_session_{inst.id}.json"
                if sf.exists():
                    sf.unlink()
            except Exception:
                pass

        self._save_to_manifest()

    async def destroy_agent_async(self, agent_id: str, delete_data: bool = True) -> None:
        """异步销毁干员：停止进程 + 从通讯录删除 + 可选删数据。"""
        inst = self._instances.get(agent_id)
        if inst is None:
            logger.warning(f"干员 {agent_id} 不存在")
            return

        # 先停止进程
        if inst.running:
            await self._stop_instance(inst)

        # 再从通讯录删除
        self._instances.pop(agent_id, None)

        if delete_data:
            _delete_agent_dir(inst.id)
            try:
                sf = Path.home() / "NagaAgent" / f"openclaw_session_{inst.id}.json"
                if sf.exists():
                    sf.unlink()
            except Exception:
                pass

        self._save_to_manifest()
        logger.info(f"干员 [{inst.name}] 已销毁 delete_data={delete_data}")

    def rename_agent(self, agent_id: str, new_name: str) -> bool:
        """重命名干员（只改 manifest，目录用 UUID 不变）。"""
        inst = self._instances.get(agent_id)
        if inst is None:
            return False

        old_name = inst.name
        if old_name == new_name:
            return True

        inst.name = new_name
        self._save_to_manifest()

        logger.info(f"干员 [{old_name}] → [{new_name}]")
        return True

    def list_agents(self) -> List[dict]:
        """返回通讯录中的所有干员（不管进程是否在跑）。"""
        return [
            {
                "id": inst.id,
                "name": inst.name,
                "running": inst.running,
                "created_at": inst.created_at,
                "character_template": inst.character_template,
                "engine": inst.engine,
            }
            for inst in self._instances.values()
        ]

    def get_instance(self, agent_id: str) -> Optional[AgentInstance]:
        return self._instances.get(agent_id)

    # ── 进程管理（按需启动） ──

    async def ensure_running(self, agent_id: str) -> AgentInstance:
        """确保干员进程在运行。若未启动则按需启动。"""
        inst = self._instances.get(agent_id)
        if inst is None:
            raise RuntimeError(f"干员 {agent_id} 不存在")
        if inst.engine != "openclaw":
            raise RuntimeError(f"干员 [{inst.name}] 使用的是 {inst.engine}，暂未接入独立 OpenClaw 运行时")

        if inst.running and inst.client is not None:
            # 检查端口是否仍可达
            if inst.port > 0 and self._check_port(inst.port):
                return inst
            # 端口不通了，标记为未运行，重新启动
            logger.info(f"[{inst.name}] 端口 {inst.port} 不可达，重新启动")
            inst.running = False

        # 启动进程
        await self._start_instance(inst)
        return inst

    async def _start_instance(self, inst: AgentInstance) -> None:
        """启动干员 Gateway 进程。"""
        # 判断是否作为 primary
        has_primary = any(i.running and i.primary for i in self._instances.values())
        is_primary = not has_primary

        self._ensure_gateway_config()

        if is_primary:
            port = self._get_primary_port()
            logger.info(f"启动干员 [{inst.name}] 主 Gateway 端口={port}")

            if not self._check_port(port):
                try:
                    _kill_stale_on_port(port)
                    await asyncio.sleep(0.5)
                except Exception:
                    pass
                await self._runtime.start_gateway()

            gateway_token, hooks_token = self._get_tokens()
            gw_url = f"http://127.0.0.1:{port}"
            client = OpenClawClient(OpenClawConfig(
                gateway_url=gw_url,
                gateway_token=gateway_token,
                hooks_token=hooks_token,
                timeout=120,
            ))
            client._default_session_key = f"agent:main:{inst.id}"
            client._SESSION_FILE = Path.home() / "NagaAgent" / f"openclaw_session_{inst.id}.json"

            # 等待端口就绪
            for wait in range(15):
                if self._check_port(port):
                    logger.info(f"  主 Gateway 端口 {port} 已就绪 (等待 {wait}s)")
                    break
                if wait == 0:
                    logger.info(f"  等待主 Gateway 端口 {port} 就绪...")
                await asyncio.sleep(1)
            else:
                logger.warning(f"  主 Gateway 端口 {port} 15s 内未就绪")

            inst.port = port
            inst.client = client
            inst.primary = True
            inst.process = None
        else:
            port = self._allocate_port()
            logger.info(f"启动干员 [{inst.name}] 端口={port}")

            self._ensure_gateway_config()
            process = await self._runtime.start_gateway_on_port(port)
            if process is None:
                self._release_port(port)
                raise RuntimeError(f"无法在端口 {port} 启动 Gateway 进程")

            gateway_token, hooks_token = self._get_tokens()
            gw_url = f"http://127.0.0.1:{port}"
            client = OpenClawClient(OpenClawConfig(
                gateway_url=gw_url,
                gateway_token=gateway_token,
                hooks_token=hooks_token,
                timeout=120,
            ))
            client._default_session_key = f"agent:main:{inst.id}"
            client._SESSION_FILE = Path.home() / "NagaAgent" / f"openclaw_session_{inst.id}.json"

            inst.port = port
            inst.client = client
            inst.primary = False
            inst.process = process

        inst.running = True
        logger.info(f"干员 [{inst.name}] 进程已启动 port={inst.port} primary={inst.primary}")

    async def _stop_instance(self, inst: AgentInstance) -> None:
        """停止干员进程（不删除通讯录条目）。"""
        if not inst.running:
            return

        logger.info(f"停止干员 [{inst.name}] port={inst.port} primary={inst.primary}")

        if inst.primary:
            # 主实例：仅移除引用，不停止进程
            inst.running = False
            inst.client = None
            return

        if inst.client:
            try:
                await inst.client.close()
            except Exception as e:
                logger.warning(f"关闭客户端失败: {e}")
            inst.client = None

        if inst.process is not None:
            try:
                if inst.process.returncode is None:
                    inst.process.terminate()
                    try:
                        await asyncio.wait_for(inst.process.wait(), timeout=10)
                    except asyncio.TimeoutError:
                        inst.process.kill()
                        await inst.process.wait()
            except Exception as e:
                logger.error(f"停止进程失败: {e}")
            inst.process = None

        self._release_port(inst.port)
        inst.port = 0
        inst.running = False
        inst.primary = False

    async def destroy_all(self) -> None:
        """停止所有运行中的进程（关闭应用时调用）。"""
        for inst in list(self._instances.values()):
            if inst.running:
                await self._stop_instance(inst)

    # ── 兼容旧 API ──

    async def create_instance(self, name: Optional[str] = None, instance_id: Optional[str] = None, _restoring: bool = False) -> AgentInstance:
        """兼容旧接口：创建干员并立即启动。"""
        inst = self.create_agent(name, instance_id)
        await self.ensure_running(inst.id)
        return inst

    async def destroy_instance(self, instance_id: str) -> None:
        """兼容旧接口。"""
        await self.destroy_agent_async(instance_id, delete_data=True)

    def list_instances(self) -> List[dict]:
        """兼容旧接口。"""
        return self.list_agents()

    def rename_instance(self, instance_id: str, new_name: str) -> bool:
        """兼容旧接口。"""
        return self.rename_agent(instance_id, new_name)

    # ── Manifest 持久化 ──

    def _save_to_manifest(self):
        data = {
            "agents": [
                {
                    "id": inst.id,
                    "name": inst.name,
                    "created_at": inst.created_at,
                    "character_template": inst.character_template,
                    "engine": inst.engine,
                }
                for inst in self._instances.values()
            ],
            "next_agent_number": self._agent_counter,
        }
        try:
            _save_manifest(data)
        except Exception as e:
            logger.warning(f"保存 manifest 失败: {e}")

    def restore_from_manifest(self):
        """从 manifest 恢复通讯录（不启动进程）。返回角色列表。"""
        manifest = _load_manifest()
        agents = manifest.get("agents", [])

        saved_counter = manifest.get("next_agent_number", 0)
        if saved_counter > self._agent_counter:
            self._agent_counter = saved_counter

        restored = 0
        for saved in agents:
            agent_id = saved.get("id")
            if not agent_id or agent_id in self._instances:
                continue

            name = saved.get("name", f"干员{self._agent_counter + 1}")
            character_template = saved.get("character_template")
            engine = normalize_agent_engine(saved.get("engine"))
            # 确保目录存在（用 UUID）
            _init_agent_dir(agent_id, name, character_template, engine=engine)

            inst = AgentInstance(
                id=agent_id,
                name=name,
                created_at=saved.get("created_at", time.time()),
                character_template=character_template,
                engine=engine,
            )
            self._instances[agent_id] = inst
            restored += 1

        if restored:
            logger.info(f"从 manifest 恢复了 {restored} 个干员（通讯录条目，未启动进程）")

        return self.list_agents()

    # ── 消息发送 ──

    async def send_message(
        self,
        instance_id: str,
        message: str,
        timeout: int = 120,
        session_key: Optional[str] = None,
        name: Optional[str] = None,
    ) -> dict:
        """通过指定实例发送消息。自动 ensure_running。"""
        try:
            inst = await self.ensure_running(instance_id)
        except RuntimeError as e:
            return {"success": False, "error": str(e)}

        if not inst.client:
            return {"success": False, "error": f"干员 [{inst.name}] 客户端未就绪"}

        # 非主实例检查进程存活
        if not inst.primary and inst.process is not None and inst.process.returncode is not None:
            return {"success": False, "error": f"干员 [{inst.name}] 进程已退出"}

        logger.info(
            f"发送消息到 [{inst.name}] port={inst.port} primary={inst.primary} "
            f"gateway_url={inst.client.config.gateway_url} msg={message[:50]}..."
        )

        # 端口不可达 → 尝试重启
        if not self._check_port(inst.port):
            logger.info(f"[{inst.name}] 端口 {inst.port} 不可达，重新启动...")
            started = await self._try_start_gateway(inst)
            if not started:
                return {
                    "success": False,
                    "retry": True,
                    "error": f"Gateway 端口 {inst.port} 正在启动中",
                }

        try:
            agent_workspace = str(_get_agents_dir() / instance_id)
            task = await inst.client.send_message(
                message=message,
                session_key=session_key,
                workspace=agent_workspace,
                name=name,
                wake_mode="now",
                deliver=False,
                timeout_seconds=timeout,
            )
            return {
                "success": task.status.value != "failed",
                "reply": task.result.get("reply") if task.result else None,
                "replies": task.result.get("replies") if task.result else None,
                "error": task.error,
            }
        except Exception as e:
            logger.error(f"发送消息到 [{inst.name}] 失败: {e}")
            return {"success": False, "error": str(e)}

    async def _try_start_gateway(self, inst: AgentInstance) -> bool:
        self._ensure_gateway_config()
        try:
            _kill_stale_on_port(inst.port)
            await asyncio.sleep(0.5)
        except Exception:
            pass

        if inst.primary:
            ok = await self._runtime.start_gateway()
            return ok and self._check_port(inst.port)
        else:
            process = await self._runtime.start_gateway_on_port(inst.port)
            if process is not None and self._check_port(inst.port):
                inst.process = process
                return True
            return False

    # ── 流式发送 ──

    # Skill/Tool 调用检测（LLM 输出文本格式而非原生 ToolCall）
    import re as _re
    import json as _json_lib

    _SKILL_XML_RE = _re.compile(
        r"<skill\b[^>]*>\s*<name>\s*(\S+?)\s*</name>"
        r"(?:\s*<location>[^<]*</location>)?"
        r"[\s\S]*?</skill>",
        _re.IGNORECASE,
    )
    _SKILL_CALL_XML_RE = _re.compile(
        r"<skill_call>\s*<skill_name>\s*(\S+?)\s*</skill_name>"
        r"[\s\S]*?</skill_call>",
        _re.IGNORECASE,
    )
    _JSON_TOOL_RE = _re.compile(
        r'\{\s*"action"\s*:\s*"([^"]+)"\s*,\s*"args"\s*:\s*(\{[^}]*\})\s*\}',
        _re.IGNORECASE,
    )
    # 检测伪代码工具调用: await read(...), await search(...) 等
    _PSEUDO_CODE_RE = _re.compile(
        r'(?:await\s+)?(\w+)\s*\(\s*["\']([^"\']+)["\']\s*\)',
        _re.IGNORECASE,
    )
    # 检测特殊分隔符工具调用格式（Qwen/GLM 等）
    _SPECIAL_TOOL_RE = _re.compile(
        r'<\|tool_call_begin\|>functions\.(\w+):\d+<\|tool_call_argument_begin\|>(\{[^}]+\})',
        _re.IGNORECASE,
    )
    _SPECIAL_TOOL_MARKERS = (
        "<|tool_calls_section_begin|>",
        "<|tool_calls_section_end|>",
        "<|tool_call_begin|>",
        "<|tool_call_argument_begin|>",
        "<|tool_call_end|>",
    )

    def _detect_tool_invocation(self, text: str) -> dict | None:
        """检测 skill XML、JSON、伪代码或特殊分隔符工具调用。返回 {"type": "...", "name": "...", "args": {...}} 或 None。"""
        # 优先检测 skill XML
        m = self._SKILL_XML_RE.search(text)
        if m:
            return {"type": "skill", "name": m.group(1)}
        m = self._SKILL_CALL_XML_RE.search(text)
        if m:
            return {"type": "skill", "name": m.group(1)}

        # 检测特殊分隔符格式（Qwen/GLM）
        m = self._SPECIAL_TOOL_RE.search(text)
        if m:
            try:
                tool_name = m.group(1)
                args = self._json_lib.loads(m.group(2))
                return {"type": "special", "name": tool_name, "args": args}
            except:
                pass

        # 检测 JSON 工具调用
        m = self._JSON_TOOL_RE.search(text)
        if m:
            try:
                args = self._json_lib.loads(m.group(2))
                return {"type": "json", "name": m.group(1), "args": args}
            except:
                pass

        # 检测伪代码工具调用
        m = self._PSEUDO_CODE_RE.search(text)
        if m:
            func_name = m.group(1).lower()
            arg = m.group(2)
            skill_map = {
                "read": "read",
                "search": "web-search",
                "websearch": "web-search",
                "web_search": "web-search",
            }
            if func_name in skill_map:
                return {"type": "pseudo", "name": skill_map[func_name], "original": func_name, "arg": arg}

        return None

    def _strip_tool_invocation(self, text: str) -> str:
        """移除文本中所有 skill XML 和 JSON 工具调用。"""
        text = self._SKILL_XML_RE.sub("", text)
        text = self._SKILL_CALL_XML_RE.sub("", text)
        text = self._JSON_TOOL_RE.sub("", text)
        return text.strip()

    def _sanitize_stream_content(self, text: str) -> str:
        """移除流式内容里残留的工具分隔符前缀。"""
        if not text:
            return text
        sanitized = text
        for marker in self._SPECIAL_TOOL_MARKERS:
            sanitized = sanitized.replace(marker, "")
        return sanitized

    @staticmethod
    def _read_skill_file(skill_name: str) -> str | None:
        """读取 skills/{name}/SKILL.md。"""
        project_root = Path(__file__).resolve().parent.parent.parent
        skill_md = project_root / "skills" / skill_name / "SKILL.md"
        if skill_md.is_file():
            return skill_md.read_text(encoding="utf-8")
        return None

    async def _do_single_stream(self, http, stream_url, headers, payload, timeout, inst_name=""):
        """单轮 SSE 流。yield 中间事件，最终 yield {"type": "done"/"error", ...}。"""
        import json as _json

        async with http.stream(
            "POST", stream_url, json=payload, headers=headers, timeout=timeout + 30,
        ) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                logger.error(f"[stream] [{inst_name}] SSE 失败: {resp.status_code} {body[:200]}")
                yield {"type": "error", "text": f"Gateway 拒绝: {resp.status_code}"}
                return

            full_text = ""
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = _json.loads(data_str)
                except _json.JSONDecodeError:
                    continue

                chunk_type = chunk.get("type", "")
                chunk_text = chunk.get("text", "")
                logger.info(f"[stream] [{inst_name}] 收到事件: type={chunk_type}, chunk={chunk}")

                if chunk_type == "content":
                    chunk_text = self._sanitize_stream_content(chunk_text)
                    full_text += chunk_text
                    yield {"type": "content", "text": chunk_text}
                elif chunk_type == "done":
                    final = self._sanitize_stream_content((full_text or chunk_text)).strip()
                    yield {"type": "done", "text": final}
                    return
                elif chunk_type == "error":
                    yield {"type": "error", "text": chunk_text}
                    return
                elif chunk_type == "status":
                    yield {"type": "status", "text": chunk_text}
                elif chunk_type == "tool_call":
                    yield {
                        "type": "tool_call",
                        "name": chunk.get("name", ""),
                        "text": chunk_text,
                        "toolCallId": chunk.get("toolCallId", ""),
                        "args": chunk.get("args"),
                    }
                elif chunk_type == "tool_result":
                    yield {
                        "type": "tool_result",
                        "name": chunk.get("name", ""),
                        "text": chunk_text,
                        "toolCallId": chunk.get("toolCallId", ""),
                        "isError": bool(chunk.get("isError", False)),
                        "result": chunk.get("result"),
                    }

            # 流结束但没有 done event
            if full_text:
                final = self._sanitize_stream_content(full_text).strip()
                yield {"type": "done", "text": final}
            else:
                yield {"type": "error", "text": "流结束但无回复"}

    async def send_message_stream(self, instance_id: str, message: str, timeout: int = 120):
        """流式发送消息。自动 ensure_running + 自动检测并执行 skill。"""
        import httpx

        inst = self._instances.get(instance_id)
        if inst is None:
            yield {"type": "error", "text": f"干员 {instance_id} 不存在"}
            return

        # 确保进程在运行
        if not inst.running or not inst.client:
            yield {"type": "status", "text": "干员苏醒中"}
            try:
                inst = await self.ensure_running(instance_id)
            except Exception as e:
                yield {"type": "error", "text": f"启动失败: {e}"}
                return

        logger.info(f"[stream] [{inst.name}] 开始: {message[:50]}...")

        if not inst.primary and inst.process is not None and inst.process.returncode is not None:
            yield {"type": "error", "text": f"干员 [{inst.name}] 进程已退出"}
            return

        # 端口不可达 → 启动 Gateway
        if not self._check_port(inst.port):
            yield {"type": "status", "text": "干员苏醒中"}
            started = await self._try_start_gateway(inst)
            if not started:
                yield {"type": "error", "text": f"Gateway 端口 {inst.port} 启动失败"}
                return

        yield {"type": "status", "text": "思考中"}

        client = inst.client
        session_key = client._default_session_key
        if not session_key:
            session_key = f"agent:main:{instance_id}"
            client._default_session_key = session_key

        stream_url = f"{client.config.gateway_url}/hooks/agent/stream"
        headers = client.config.get_hooks_headers()
        # 传递干员独立 workspace 目录，OpenClaw 将用它加载 AGENTS.md/SOUL.md 等
        agent_workspace = str(_get_agents_dir() / instance_id)
        payload = {
            "message": message,
            "sessionKey": session_key,
            "wakeMode": "now",
            "deliver": False,
            "timeoutSeconds": 0,
            "workspace": agent_workspace,
        }

        logger.info(f"[stream] [{inst.name}] SSE → {stream_url} (使用 OpenClaw 原生工具)")

        try:
            async with httpx.AsyncClient() as http:
                # 直接透传 OpenClaw 的原生响应，让 OpenClaw 处理工具调用
                async for event in self._do_single_stream(
                    http, stream_url, headers, payload, timeout, inst.name
                ):
                    yield event

        except httpx.TimeoutException:
            logger.warning(f"[stream] [{inst.name}] SSE 超时 {timeout}s")
            yield {"type": "error", "text": "等待回复超时"}
        except Exception as e:
            logger.error(f"[stream] [{inst.name}] SSE 异常: {e}")
            yield {"type": "error", "text": f"连接失败: {e}"}

    @staticmethod
    def _check_port(port: int, host: str = "127.0.0.1") -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                return s.connect_ex((host, port)) == 0
        except Exception:
            return False

    @staticmethod
    def _ensure_gateway_config():
        try:
            from .llm_config_bridge import ensure_hooks_allow_request_session_key
            ensure_hooks_allow_request_session_key(auto_create=False)
        except Exception:
            pass
