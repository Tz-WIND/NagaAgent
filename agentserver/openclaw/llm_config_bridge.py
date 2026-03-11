#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenClaw 配置自动生成 + LLM 桥接

当 ~/.openclaw/openclaw.json 不存在时，自动生成最小可用配置，
并注入 Naga 的 LLM 设置（api_key / base_url / model）。
不再依赖 `openclaw onboard` 命令。
"""

import json
import logging
import secrets
import os
import shutil
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger("openclaw.bridge")


def _get_openclaw_paths():
    """统一使用 OpenClaw 默认目录 (~/.openclaw)，避免与 CLI 读取路径不一致。"""
    home_override = os.environ.get("OPENCLAW_HOME", "").strip()
    config_dir = Path(home_override).expanduser() if home_override else (Path.home() / ".openclaw")
    return config_dir, config_dir / "openclaw.json"


OPENCLAW_CONFIG_DIR, OPENCLAW_CONFIG_FILE = _get_openclaw_paths()


def _migrate_legacy_config_if_needed() -> None:
    """兼容历史路径：%APPDATA%/NagaAgent/openclaw -> ~/.openclaw"""
    if OPENCLAW_CONFIG_FILE.exists():
        return
    try:
        from system.config import get_data_dir

        legacy_dir = get_data_dir() / "openclaw"
        legacy_cfg = legacy_dir / "openclaw.json"
        if not legacy_cfg.exists():
            return

        OPENCLAW_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy_cfg, OPENCLAW_CONFIG_FILE)
        logger.info(f"已迁移 OpenClaw 配置: {legacy_cfg} -> {OPENCLAW_CONFIG_FILE}")
    except Exception as e:
        logger.warning(f"迁移历史 OpenClaw 配置失败（忽略）: {e}")


def _apply_hooks_compat_patch(config_data: Dict[str, Any]) -> bool:
    """清理 hooks 中 OpenClaw 不认识的字段，防止配置校验失败。"""
    hooks = config_data.get("hooks", {})
    changed = False
    # allowRequestSessionKey 在新版 OpenClaw 中是 unrecognized key，需删除
    if "allowRequestSessionKey" in hooks:
        del hooks["allowRequestSessionKey"]
        changed = True
    return changed


def _apply_hooks_path_patch(config_data: Dict[str, Any]) -> bool:
    """确保 hooks.path 已显式设置为 /hooks，避免 Gateway 不注册 hooks 路由导致405。"""
    hooks = config_data.setdefault("hooks", {})
    if hooks.get("path") == "/hooks":
        return False
    hooks["path"] = "/hooks"
    return True


def _apply_gateway_mode_compat_patch(config_data: Dict[str, Any]) -> bool:
    """
    兼容 OpenClaw Gateway 启动约束：
    当 gateway.mode 缺失/为空时补齐为 local，避免启动被阻塞。
    """
    gateway = config_data.setdefault("gateway", {})
    mode = gateway.get("mode")
    if isinstance(mode, str) and mode.strip():
        return False
    gateway["mode"] = "local"
    return True


NAGA_GATEWAY_PORT = 20789


def _get_gateway_port() -> int:
    """从 system.config 读取端口（单一来源），import 失败则回退常量。"""
    try:
        from system.config import config as _cfg
        return _cfg.openclaw.gateway_port
    except Exception:
        return NAGA_GATEWAY_PORT


def _apply_gateway_port_patch(config_data: Dict[str, Any]) -> bool:
    """确保 gateway.port 与 NagaAgent 配置一致。"""
    port = _get_gateway_port()
    gateway = config_data.setdefault("gateway", {})
    if gateway.get("port") == port:
        return False
    gateway["port"] = port
    return True


def ensure_hooks_allow_request_session_key(auto_create: bool = False) -> bool:
    """
    确保 openclaw.json 中启用 hooks.allowRequestSessionKey=true。

    Args:
        auto_create: 当配置不存在时是否自动创建最小配置

    Returns:
        True 表示已满足条件（已存在或已修复），False 表示修复失败
    """
    if not OPENCLAW_CONFIG_FILE.exists():
        if not auto_create:
            logger.debug("openclaw.json 不存在，跳过 hooks.allowRequestSessionKey 兼容补丁")
            return False
        if not ensure_openclaw_config():
            return False

    try:
        config_data = json.loads(OPENCLAW_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"读取 openclaw.json 失败，无法应用 hooks 兼容补丁: {e}")
        return False

    changed = _apply_hooks_compat_patch(config_data)
    if not changed:
        return True

    try:
        OPENCLAW_CONFIG_FILE.write_text(
            json.dumps(config_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("已启用 OpenClaw hooks.allowRequestSessionKey=true（兼容外部 sessionKey）")
        return True
    except Exception as e:
        logger.error(f"写入 openclaw.json 失败，hooks 兼容补丁未生效: {e}")
        return False


def ensure_gateway_local_mode(auto_create: bool = False) -> bool:
    """
    确保 openclaw.json 的 gateway.mode 已设置为 local（仅在缺失时补齐）。

    Args:
        auto_create: 当配置不存在时是否自动创建最小配置

    Returns:
        True 表示已满足条件（已存在或已修复），False 表示修复失败
    """
    if not OPENCLAW_CONFIG_FILE.exists():
        if not auto_create:
            logger.debug("openclaw.json 不存在，跳过 gateway.mode 兼容补丁")
            return False
        if not ensure_openclaw_config():
            return False

    try:
        config_data = json.loads(OPENCLAW_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"读取 openclaw.json 失败，无法应用 gateway.mode 兼容补丁: {e}")
        return False

    changed = _apply_gateway_mode_compat_patch(config_data)
    if not changed:
        return True

    try:
        OPENCLAW_CONFIG_FILE.write_text(
            json.dumps(config_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("已补齐 OpenClaw gateway.mode=local（兼容旧配置）")
        return True
    except Exception as e:
        logger.error(f"写入 openclaw.json 失败，gateway.mode 兼容补丁未生效: {e}")
        return False


def ensure_hooks_path(auto_create: bool = False) -> bool:
    """确保 openclaw.json 的 hooks.path 已显式设置为 /hooks。"""
    if not OPENCLAW_CONFIG_FILE.exists():
        if not auto_create:
            return False
        if not ensure_openclaw_config():
            return False

    try:
        config_data = json.loads(OPENCLAW_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"读取 openclaw.json 失败，无法应用 hooks.path 补丁: {e}")
        return False

    changed = _apply_hooks_path_patch(config_data)
    if not changed:
        return True

    try:
        OPENCLAW_CONFIG_FILE.write_text(
            json.dumps(config_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("已补齐 OpenClaw hooks.path=/hooks（避免 Gateway 不注册 hooks 路由）")
        return True
    except Exception as e:
        logger.error(f"写入 openclaw.json 失败，hooks.path 补丁未生效: {e}")
        return False


def ensure_gateway_port(auto_create: bool = False) -> bool:
    """确保 openclaw.json 的 gateway.port 与 NagaAgent 配置一致。"""
    if not OPENCLAW_CONFIG_FILE.exists():
        if not auto_create:
            return False
        if not ensure_openclaw_config():
            return False

    try:
        config_data = json.loads(OPENCLAW_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"读取 openclaw.json 失败，无法应用 gateway.port 补丁: {e}")
        return False

    changed = _apply_gateway_port_patch(config_data)
    if not changed:
        return True

    port = _get_gateway_port()
    try:
        OPENCLAW_CONFIG_FILE.write_text(
            json.dumps(config_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"已将 gateway.port 更新为 {port}")
        return True
    except Exception as e:
        logger.error(f"写入 openclaw.json 失败，gateway.port 补丁未生效: {e}")
        return False


def ensure_openclaw_config() -> bool:
    """
    确保 openclaw.json 存在，不存在则自动生成最小可用配置。

    Returns:
        是否成功（已存在或新建成功）
    """
    _migrate_legacy_config_if_needed()

    if OPENCLAW_CONFIG_FILE.exists():
        logger.debug("openclaw.json 已存在，跳过生成")
        return True

    try:
        OPENCLAW_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        gateway_token = secrets.token_hex(32)
        hooks_token = secrets.token_hex(32)

        minimal_config = {
            "gateway": {
                "mode": "local",
                "port": _get_gateway_port(),
                "bind": "loopback",
                "auth": {"mode": "token", "token": gateway_token},
            },
            "hooks": {
                "enabled": True,
                "path": "/hooks",
                "token": hooks_token,
            },
            "tools": {"allow": ["*"]},
            "agents": {
                "defaults": {
                    "workspace": str(OPENCLAW_CONFIG_DIR / "workspace"),
                    "maxConcurrent": 4,
                }
            },
        }

        OPENCLAW_CONFIG_FILE.write_text(
            json.dumps(minimal_config, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"已自动生成 openclaw.json: {OPENCLAW_CONFIG_FILE}")
        return True

    except Exception as e:
        logger.error(f"自动生成 openclaw.json 失败: {e}")
        return False


def inject_naga_llm_config() -> bool:
    """
    将 Naga 的 LLM + 搜索 配置注入 openclaw.json。

    - LLM: api_key / base_url / model → models.providers + agents.defaults.model
    - 搜索: online_search.search_api_key → env.BRAVE_API_KEY

    Returns:
        是否注入成功
    """
    if not OPENCLAW_CONFIG_FILE.exists():
        logger.warning("openclaw.json 不存在，无法注入配置")
        return False

    try:
        from system.config import config as naga_config

        config_data = json.loads(OPENCLAW_CONFIG_FILE.read_text(encoding="utf-8"))
        _apply_hooks_compat_patch(config_data)
        _apply_gateway_mode_compat_patch(config_data)
        _apply_gateway_port_patch(config_data)

        # ── LLM Provider ──
        # 已登录或有 refresh_token（登录态可恢复）→ 用 NagaBusiness 网关
        try:
            from apiserver.naga_auth import is_authenticated, has_refresh_token, get_access_token, NAGA_MODEL_URL
            use_business = is_authenticated() or has_refresh_token()
            if use_business:
                base_url = NAGA_MODEL_URL
                api_key = get_access_token() or naga_config.api.api_key
                logger.info(f"使用 NagaBusiness 网关: {base_url}")
            else:
                base_url = naga_config.api.base_url.rstrip("/")
                api_key = naga_config.api.api_key
                logger.info(f"使用静态配置: {base_url}")
        except ImportError:
            base_url = naga_config.api.base_url.rstrip("/")
            api_key = naga_config.api.api_key
            api_key = naga_config.api.api_key

        provider_name = "naga"
        model_id = naga_config.api.model
        full_model_id = f"{provider_name}/{model_id}"

        models_config = config_data.setdefault("models", {})
        models_config["mode"] = "merge"
        providers = models_config.setdefault("providers", {})
        providers[provider_name] = {
            "baseUrl": base_url,
            "apiKey": api_key,
            "auth": "api-key",
            "api": "openai-completions",
            "models": [
                {
                    "id": model_id,
                    "name": model_id,
                    "reasoning": False,
                    "input": ["text"],
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    "contextWindow": 128000,
                    "maxTokens": naga_config.api.max_tokens,
                }
            ],
        }

        # 设置为默认模型
        agents = config_data.setdefault("agents", {})
        defaults = agents.setdefault("defaults", {})
        model = defaults.setdefault("model", {})
        model["primary"] = full_model_id

        # ── 搜索 API Key（Brave Search）──
        # 同步到 env.BRAVE_API_KEY + tools.web.search.apiKey 两处
        # 注：OpenClaw 不支持自定义 Brave base URL，但主路径搜索走 NagaAgent 本地执行
        search_key = getattr(naga_config.online_search, "search_api_key", "")
        env_section = config_data.setdefault("env", {})
        if search_key:
            env_section["BRAVE_API_KEY"] = search_key
            tools_section = config_data.setdefault("tools", {})
            web_section = tools_section.setdefault("web", {})
            search_section = web_section.setdefault("search", {})
            search_section["apiKey"] = search_key
        else:
            env_section.pop("BRAVE_API_KEY", None)

        OPENCLAW_CONFIG_FILE.write_text(
            json.dumps(config_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"已注入 Naga 配置: model={full_model_id}, search_key={'已配置' if search_key else '未配置'}")
        return True

    except Exception as e:
        logger.error(f"注入配置失败: {e}")
        return False
