#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent Server配置文件 - 重构版
提供客观、实用的配置管理
"""

from dataclasses import dataclass
from typing import Optional

# ============ 服务器配置 ============

# 从主配置读取端口
try:
    from system.config import get_server_port
    AGENT_SERVER_PORT = get_server_port("agent_server")
except ImportError:
    AGENT_SERVER_PORT = 8001  # 回退默认值

# ============ OpenClaw 配置 ============

@dataclass
class OpenClawConfig:
    """OpenClaw 集成配置

    官方文档: https://docs.openclaw.ai/
    """
    # Gateway 连接 - 默认端口是 18789
    gateway_url: str = "http://localhost:18789"
    # 认证 token (对应 gateway.auth.token 或 gateway.auth.password)
    token: Optional[str] = None
    # 请求超时时间（秒）
    timeout: int = 120

    # 默认参数
    default_model: Optional[str] = None         # 默认模型
    default_channel: str = "last"               # 默认消息通道

    # 功能开关
    enabled: bool = True                        # 是否启用 OpenClaw 集成

# 默认 OpenClaw 配置实例
DEFAULT_OPENCLAW_CONFIG = OpenClawConfig()

# ============ 全局配置管理 ============

@dataclass
class AgentServerConfig:
    """Agent服务器全局配置"""
    # 服务器配置
    host: str = "0.0.0.0"
    port: int = None

    # 子模块配置
    openclaw: OpenClawConfig = None

    # 日志配置
    log_level: str = "INFO"
    enable_debug_logs: bool = False

    def __post_init__(self):
        # 设置默认端口
        if self.port is None:
            self.port = AGENT_SERVER_PORT

        # 设置默认子配置
        if self.openclaw is None:
            self.openclaw = DEFAULT_OPENCLAW_CONFIG

# 全局配置实例
config = AgentServerConfig()

# ============ 配置访问函数 ============

def get_openclaw_config() -> OpenClawConfig:
    """获取 OpenClaw 配置"""
    return config.openclaw

def update_config(**kwargs):
    """更新配置"""
    for key, value in kwargs.items():
        if hasattr(config, key):
            setattr(config, key, value)
        else:
            raise ValueError(f"未知配置项: {key}")

# ============ 向后兼容 ============

# 保持向后兼容的配置常量
AGENT_SERVER_HOST = config.host
AGENT_SERVER_PORT = config.port
