"""
Heartbeat 调度器
负责定时触发心跳检查，调用 Naga LLM，按规则决定是否推送 UI。
"""

import asyncio
import re
import time
import logging
from datetime import datetime, time as dt_time
from typing import Optional

from .config import HeartbeatConfig
from .prompt import HEARTBEAT_SYSTEM_PROMPT, HEARTBEAT_CHECKLIST

logger = logging.getLogger(__name__)

# HEARTBEAT_OK 标记 — 响应中包含此标记且长度 ≤ ack_max_chars 时静默丢弃
_ACK_MARKER = "HEARTBEAT_OK"

# checklist 指令正则
_RE_ADD_ITEM = re.compile(r"^\[ADD_ITEM\]\s*(.+)$", re.MULTILINE)
_RE_DONE_ITEM = re.compile(r"^\[DONE_ITEM\]\s*(\S+)$", re.MULTILINE)
_RE_DISMISS_ITEM = re.compile(r"^\[DISMISS_ITEM\]\s*(\S+)$", re.MULTILINE)


class HeartbeatScheduler:
    """心跳调度器"""

    def __init__(self, config: HeartbeatConfig):
        self.config = config
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_heartbeat_time: float = 0.0
        self._last_heartbeat_result: Optional[str] = None
        self._heartbeat_count: int = 0
        # 事件驱动心跳
        self._conversation_active: bool = False
        self._countdown_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self):
        """启动调度器"""
        if self._running:
            logger.warning("[Heartbeat] 调度器已在运行")
            return

        self._running = True
        self._task = asyncio.create_task(self._schedule_loop())
        logger.info(
            f"[Heartbeat] 调度器已启动 (事件驱动, "
            f"对话后延迟: {self.config.post_conversation_delay_minutes}min, "
            f"活跃时段: {self.config.active_hours_start}-{self.config.active_hours_end})"
        )

    async def stop(self):
        """停止调度器"""
        if not self._running:
            return

        self._running = False
        # 取消倒计时
        if self._countdown_task and not self._countdown_task.done():
            self._countdown_task.cancel()
            self._countdown_task = None
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[Heartbeat] 调度器已停止")

    # ------------------------------------------------------------------
    # 主循环（事件驱动）
    # ------------------------------------------------------------------

    async def _schedule_loop(self):
        """事件驱动主循环 — 保活，实际心跳由对话事件触发"""
        while self._running:
            try:
                await asyncio.sleep(60)  # 保活
            except asyncio.CancelledError:
                logger.info("[Heartbeat] 调度循环被取消")
                break
            except Exception as e:
                logger.error(f"[Heartbeat] 调度循环异常: {e}", exc_info=True)
                await asyncio.sleep(60)

    # ------------------------------------------------------------------
    # 对话生命周期事件
    # ------------------------------------------------------------------

    def on_conversation_started(self):
        """对话开始 → 取消倒计时"""
        self._conversation_active = True
        if self._countdown_task and not self._countdown_task.done():
            self._countdown_task.cancel()
            self._countdown_task = None
            logger.info("[Heartbeat] 对话开始，已取消心跳倒计时")

    def on_conversation_ended(self):
        """对话结束 → 启动 N 分钟倒计时"""
        self._conversation_active = False
        if self._countdown_task and not self._countdown_task.done():
            self._countdown_task.cancel()
        delay_min = self.config.post_conversation_delay_minutes
        self._countdown_task = asyncio.create_task(self._countdown_then_heartbeat())
        logger.info(f"[Heartbeat] 对话结束，启动 {delay_min} 分钟倒计时")

    async def _countdown_then_heartbeat(self):
        """倒计时结束后执行心跳"""
        try:
            delay = self.config.post_conversation_delay_minutes * 60
            await asyncio.sleep(delay)
            # 时段检查 + 开关检查
            if self._is_in_active_hours() and self.config.enabled:
                logger.info("[Heartbeat] 倒计时到期，执行心跳")
                self._last_heartbeat_time = time.time()
                await self._perform_heartbeat()
            else:
                logger.info("[Heartbeat] 倒计时到期，但不在活跃时段或已禁用，跳过")
        except asyncio.CancelledError:
            logger.info("[Heartbeat] 心跳倒计时被取消（新对话开始）")

    def _is_in_active_hours(self) -> bool:
        """检查当前是否在活跃时段内"""
        try:
            now = datetime.now().time()
            start = dt_time.fromisoformat(self.config.active_hours_start)
            end = dt_time.fromisoformat(self.config.active_hours_end)

            if start < end:
                return start <= now <= end
            else:
                # 跨午夜，如 22:00-06:00
                return now >= start or now <= end
        except ValueError:
            logger.error(
                f"[Heartbeat] 活跃时段格式错误: "
                f"{self.config.active_hours_start} - {self.config.active_hours_end}"
            )
            return True  # 格式错误时不阻塞

    # ------------------------------------------------------------------
    # 心跳执行
    # ------------------------------------------------------------------

    async def _perform_heartbeat(self):
        """执行一次心跳：调用 LLM → 解析指令 → 推送 UI"""
        logger.info("[Heartbeat] 执行心跳检查...")
        self._heartbeat_count += 1

        try:
            response = await self._call_llm()
            self._last_heartbeat_result = response

            # 解析并执行 checklist 指令
            self._parse_checklist_commands(response)

            # 清除指令行，得到面向用户的纯文本
            display_text = self._strip_commands(response)

            # 判断是否静默
            is_ack = (
                _ACK_MARKER in display_text
                and len(display_text) <= self.config.ack_max_chars
            )

            if is_ack:
                logger.info("[Heartbeat] LLM 回复 HEARTBEAT_OK，静默丢弃")
            else:
                logger.info(f"[Heartbeat] LLM 有内容推送 ({len(display_text)} chars)")
                await self._notify_ui(display_text)
        except Exception as e:
            logger.error(f"[Heartbeat] 心跳执行失败: {e}", exc_info=True)

    async def _call_llm(self) -> str:
        """调用 Naga LLM

        直接复用 message_manager 的 compress 摘要 + 会话消息作为上下文，
        与主对话链路看到的上下文完全统一。
        """
        from apiserver.llm_service import get_llm_service
        from apiserver.message_manager import message_manager
        from .checklist import get_pending_items

        llm = get_llm_service()

        # ── system prompt：心跳指令 + compress 摘要 ──
        system_content = HEARTBEAT_SYSTEM_PROMPT
        session_id = self._get_active_session_id()

        if session_id:
            compress = message_manager.get_session_compress(session_id)
            if compress:
                system_content += (
                    f"\n\n以下是历史对话的压缩记录：\n<compress>\n{compress}\n</compress>"
                )

        messages = [{"role": "system", "content": system_content}]

        # ── 会话消息：直接用 compress 之后的消息，与主链路一致 ──
        if session_id:
            session_msgs = message_manager.get_messages(session_id)
            session_msgs = [m for m in session_msgs if m.get("role") != "info"]
            messages.extend(session_msgs)
            logger.info(f"[Heartbeat] 注入会话 {session_id} 的 {len(session_msgs)} 条消息")

        # ── 最终 user 消息：心跳检查指令 + checklist ──
        prompt_text = self.config.prompt.strip() or HEARTBEAT_CHECKLIST

        pending = get_pending_items()
        if pending:
            lines = ["\n\n当前待处理事项 (Checklist)："]
            for item in pending:
                tag = f"[{item.priority}]" if item.priority != "normal" else ""
                lines.append(f"- [{item.id}] {tag} {item.content}")
            prompt_text += "\n".join(lines)

        messages.append({"role": "user", "content": prompt_text})

        return await llm.chat_with_context(messages, temperature=0.3)

    @staticmethod
    def _get_active_session_id() -> Optional[str]:
        """获取最近活跃的会话 ID"""
        try:
            from apiserver.message_manager import message_manager

            candidates = [
                (sid, s)
                for sid, s in message_manager.sessions.items()
                if s.get("messages")
            ]
            if not candidates:
                return None
            candidates.sort(
                key=lambda x: x[1].get("last_activity", ""), reverse=True
            )
            return candidates[0][0]
        except Exception as e:
            logger.warning(f"[Heartbeat] 获取活跃会话失败: {e}")
            return None

    # ------------------------------------------------------------------
    # Checklist 指令解析
    # ------------------------------------------------------------------

    def _parse_checklist_commands(self, response: str):
        """解析 LLM 响应中的 checklist 操作指令并执行"""
        from .checklist import add_item, update_item

        # [ADD_ITEM] 内容
        for match in _RE_ADD_ITEM.finditer(response):
            content = match.group(1).strip()
            if content:
                add_item(content, source="llm")
                logger.info(f"[Heartbeat] LLM 新增 checklist: {content[:50]}")

        # [DONE_ITEM] item_id
        for match in _RE_DONE_ITEM.finditer(response):
            item_id = match.group(1).strip()
            if item_id:
                update_item(item_id, status="done")
                logger.info(f"[Heartbeat] LLM 完成 checklist: {item_id}")

        # [DISMISS_ITEM] item_id
        for match in _RE_DISMISS_ITEM.finditer(response):
            item_id = match.group(1).strip()
            if item_id:
                update_item(item_id, status="dismissed")
                logger.info(f"[Heartbeat] LLM 忽略 checklist: {item_id}")

    @staticmethod
    def _strip_commands(response: str) -> str:
        """移除指令行，返回面向用户的纯文本"""
        lines = response.splitlines()
        clean = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[ADD_ITEM]"):
                continue
            if stripped.startswith("[DONE_ITEM]"):
                continue
            if stripped.startswith("[DISMISS_ITEM]"):
                continue
            clean.append(line)
        return "\n".join(clean).strip()

    # ------------------------------------------------------------------
    # UI 推送
    # ------------------------------------------------------------------

    async def _notify_ui(self, response: str):
        """推送心跳结果：通过 api_server /queue/push 统一路由

        对话进行中 → 入队等待注入
        对话未进行 → api_server 直接推送 UI
        """
        try:
            import httpx
            from system.config import get_server_port

            api_port = get_server_port("api_server")
            async with httpx.AsyncClient(timeout=5.0, proxy=None) as client:
                resp = await client.post(
                    f"http://localhost:{api_port}/queue/push",
                    json={"content": response, "source": "heartbeat"},
                )
                if resp.status_code == 200:
                    result = resp.json()
                    logger.info(f"[Heartbeat] 推送结果: {result.get('status', 'unknown')}")
                else:
                    logger.warning(f"[Heartbeat] 推送返回 {resp.status_code}")
        except Exception as e:
            logger.warning(f"[Heartbeat] 推送失败: {e}")

    # ------------------------------------------------------------------
    # 手动触发
    # ------------------------------------------------------------------

    async def trigger_once(self):
        """手动触发一次心跳（忽略间隔和活跃时段检查）"""
        logger.info("[Heartbeat] 手动触发心跳")
        await self._perform_heartbeat()

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """返回调度器运行状态"""
        now = time.time()
        elapsed = now - self._last_heartbeat_time if self._last_heartbeat_time else None
        countdown_active = (
            self._countdown_task is not None
            and not self._countdown_task.done()
        )

        return {
            "running": self._running,
            "enabled": self.config.enabled,
            "mode": "event_driven",
            "post_conversation_delay_minutes": self.config.post_conversation_delay_minutes,
            "conversation_active": self._conversation_active,
            "countdown_active": countdown_active,
            "in_active_hours": self._is_in_active_hours(),
            "last_heartbeat_time": (
                datetime.fromtimestamp(self._last_heartbeat_time).isoformat()
                if self._last_heartbeat_time
                else None
            ),
            "heartbeat_count": self._heartbeat_count,
            "last_result_preview": (
                self._last_heartbeat_result[:200]
                if self._last_heartbeat_result
                else None
            ),
        }


# ======================================================================
# 全局单例
# ======================================================================

_scheduler: Optional[HeartbeatScheduler] = None
_scheduler_lock: Optional[asyncio.Lock] = None


def _get_lock() -> asyncio.Lock:
    global _scheduler_lock
    if _scheduler_lock is None:
        _scheduler_lock = asyncio.Lock()
    return _scheduler_lock


def get_heartbeat_scheduler() -> Optional[HeartbeatScheduler]:
    """获取调度器单例"""
    return _scheduler


def create_heartbeat_scheduler(config: HeartbeatConfig) -> HeartbeatScheduler:
    """创建并注册调度器单例"""
    global _scheduler
    if _scheduler is not None:
        logger.warning("[Heartbeat] 调度器已存在，将被替换（旧调度器未停止）")
    _scheduler = HeartbeatScheduler(config)
    return _scheduler


async def replace_heartbeat_scheduler_async(config: HeartbeatConfig) -> HeartbeatScheduler:
    """线程安全地替换调度器

    会停止旧调度器、创建新调度器（不自动启动）。
    """
    global _scheduler

    lock = _get_lock()
    async with lock:
        old = _scheduler
        was_running = old._running if old else False

        if old is not None:
            logger.info("[Heartbeat] 停止旧调度器...")
            await old.stop()

        _scheduler = HeartbeatScheduler(config)
        logger.info(f"[Heartbeat] 已创建新调度器 (was_running={was_running})")
        return _scheduler
