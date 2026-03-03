"""
消息队列 + 临时屏幕消息槽

对话进行中，外部消息（屏幕监测/心跳/用户中途补充）入队，
在工具执行完与下一轮 agentic loop 之间注入。

用户消息入队时清除队列中所有 screen_monitor/heartbeat 消息。
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class QueuedMessage:
    content: str
    source: str  # "user" | "screen_monitor" | "heartbeat"
    timestamp: float
    metadata: Dict = field(default_factory=dict)


class MessageQueue:
    """全局消息队列（单例）"""

    def __init__(self):
        self._queue: List[QueuedMessage] = []
        self._lock = threading.Lock()
        self._conversation_active: bool = False
        self._ephemeral_screen: Optional[QueuedMessage] = None

    # ------------------------------------------------------------------
    # 队列操作
    # ------------------------------------------------------------------

    def push(self, content: str, source: str, metadata: Optional[Dict] = None):
        """入队。source="user" 时清除队列中所有 screen_monitor/heartbeat 消息"""
        with self._lock:
            if source == "user":
                before = len(self._queue)
                self._queue = [m for m in self._queue if m.source == "user"]
                cleared = before - len(self._queue)
                if cleared:
                    logger.info(f"[MessageQueue] 用户消息入队，清除 {cleared} 条 screen_monitor/heartbeat 消息")

            msg = QueuedMessage(
                content=content,
                source=source,
                timestamp=time.time(),
                metadata=metadata or {},
            )
            self._queue.append(msg)
            logger.info(f"[MessageQueue] 入队: source={source}, len={len(self._queue)}")

    def drain(self) -> List[QueuedMessage]:
        """取出并清空队列，按 timestamp 排序返回"""
        with self._lock:
            if not self._queue:
                return []
            msgs = sorted(self._queue, key=lambda m: m.timestamp)
            self._queue.clear()
            logger.info(f"[MessageQueue] 排出 {len(msgs)} 条消息: {[m.source for m in msgs]}")
            return msgs

    # ------------------------------------------------------------------
    # 对话状态
    # ------------------------------------------------------------------

    def set_conversation_active(self, active: bool):
        self._conversation_active = active
        logger.info(f"[MessageQueue] conversation_active = {active}")

    def is_conversation_active(self) -> bool:
        return self._conversation_active

    # ------------------------------------------------------------------
    # 临时屏幕消息槽
    # ------------------------------------------------------------------

    def set_ephemeral_screen(self, content: str, metadata: Optional[Dict] = None):
        """设置/替换临时屏幕消息（不进入 message_manager）"""
        self._ephemeral_screen = QueuedMessage(
            content=content,
            source="screen_monitor",
            timestamp=time.time(),
            metadata=metadata or {},
        )
        logger.info(f"[MessageQueue] 设置临时屏幕消息 ({len(content)} chars)")

    def promote_ephemeral_screen(self) -> Optional[QueuedMessage]:
        """用户回复时，提升临时消息为正式上下文，返回消息内容并清空槽位"""
        msg = self._ephemeral_screen
        if msg:
            self._ephemeral_screen = None
            logger.info("[MessageQueue] 提升临时屏幕消息为正式上下文")
        return msg

    def clear_ephemeral_screen(self):
        self._ephemeral_screen = None

    def get_ephemeral_screen(self) -> Optional[QueuedMessage]:
        return self._ephemeral_screen


# ======================================================================
# 全局单例
# ======================================================================

_message_queue: Optional[MessageQueue] = None


def get_message_queue() -> MessageQueue:
    """获取或创建消息队列单例"""
    global _message_queue
    if _message_queue is None:
        _message_queue = MessageQueue()
    return _message_queue
