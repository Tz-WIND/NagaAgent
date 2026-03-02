"""
Heartbeat System - Naga 原生心跳机制

定时调用 Naga LLM 执行心跳检查，有事推送 UI，无事静默。
"""

from .config import HeartbeatConfig
from .config_loader import load_heartbeat_config, save_heartbeat_config
from .scheduler import (
    HeartbeatScheduler,
    get_heartbeat_scheduler,
    create_heartbeat_scheduler,
    replace_heartbeat_scheduler_async,
)
from .prompt import HEARTBEAT_SYSTEM_PROMPT, HEARTBEAT_CHECKLIST
from .checklist import (
    ChecklistItem,
    HeartbeatChecklist,
    load_checklist,
    save_checklist,
    add_item,
    update_item,
    remove_item,
    get_pending_items,
)

__all__ = [
    "HeartbeatConfig",
    "HeartbeatScheduler",
    "load_heartbeat_config",
    "save_heartbeat_config",
    "get_heartbeat_scheduler",
    "create_heartbeat_scheduler",
    "replace_heartbeat_scheduler_async",
    "HEARTBEAT_SYSTEM_PROMPT",
    "HEARTBEAT_CHECKLIST",
    # checklist
    "ChecklistItem",
    "HeartbeatChecklist",
    "load_checklist",
    "save_checklist",
    "add_item",
    "update_item",
    "remove_item",
    "get_pending_items",
]
