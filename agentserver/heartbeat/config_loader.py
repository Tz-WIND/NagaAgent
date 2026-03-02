"""
Heartbeat 配置文件加载和保存
"""

import json
import logging
from pathlib import Path

from .config import HeartbeatConfig

logger = logging.getLogger(__name__)


def get_config_path() -> Path:
    """获取配置文件路径"""
    from system.config import get_data_dir

    return get_data_dir() / "heartbeat_config.json"


def load_heartbeat_config() -> HeartbeatConfig:
    """加载配置文件，不存在则创建默认配置"""
    config_path = get_config_path()

    if not config_path.exists():
        logger.info(f"[Heartbeat] 配置文件不存在，创建默认配置: {config_path}")
        default_config = HeartbeatConfig()
        save_heartbeat_config(default_config)
        return default_config

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        cfg = HeartbeatConfig(**config_data)
        logger.info(f"[Heartbeat] 配置加载成功: enabled={cfg.enabled}")
        return cfg
    except Exception as e:
        logger.error(f"[Heartbeat] 配置加载失败: {e}，使用默认配置")
        return HeartbeatConfig()


def save_heartbeat_config(cfg: HeartbeatConfig) -> bool:
    """保存配置到文件"""
    config_path = get_config_path()

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg.model_dump(), f, ensure_ascii=False, indent=2)
        logger.info(f"[Heartbeat] 配置保存成功: {config_path}")
        return True
    except Exception as e:
        logger.error(f"[Heartbeat] 配置保存失败: {e}")
        return False
