#!/usr/bin/env python3
"""
旅行服务 — 状态管理、持久化、提示词构建、结果解析
"""

import ast
import json
import logging
import re
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ── 数据目录 ────────────────────────────────────

from system.config import get_data_dir

TRAVEL_DIR = get_data_dir() / "travel"
TRAVEL_DIR.mkdir(parents=True, exist_ok=True)

WRAPPED_CONTENT_RE = re.compile(
    r"<<<EXTERNAL_UNTRUSTED_CONTENT[^>]*>>>\s*(?:Source:[^\n]*\n)?(?:---\n)?(?P<body>.*?)<<<END_EXTERNAL_UNTRUSTED_CONTENT[^>]*>>>",
    re.DOTALL,
)
DISCOVERY_TAG_RE = re.compile(
    r"\[DISCOVERY\]\s*"
    r"url:\s*(?P<url>.+?)\s*"
    r"title:\s*(?P<title>.+?)\s*"
    r"summary:\s*(?P<summary>.+?)\s*"
    r"(?:tags:\s*(?P<tags>.+?)\s*)?"
    r"\[/DISCOVERY\]",
    re.DOTALL,
)
SOCIAL_TAG_RE = re.compile(
    r"\[SOCIAL\]\s*"
    r"type:\s*(?P<type>.+?)\s*"
    r"(?:post_id:\s*(?P<post_id>.+?)\s*)?"
    r"content_preview:\s*(?P<content_preview>.+?)\s*"
    r"\[/SOCIAL\]",
    re.DOTALL,
)

BROWSER_ACTION_COSTS: dict[str, int] = {
    "status": 1,
    "start": 3,
    "profiles": 1,
    "tabs": 2,
    "open": 6,
    "focus": 1,
    "close": 1,
    "snapshot": 8,
    "screenshot": 6,
    "navigate": 6,
    "console": 5,
    "pdf": 5,
    "upload": 4,
    "dialog": 2,
    "act": 10,
}
TOOL_BASE_COSTS: dict[str, int] = {
    "web_search": 24,
    "browser": 8,
}


# ── 数据模型 ────────────────────────────────────


class TravelStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TravelDiscovery(BaseModel):
    url: str
    title: str
    summary: str
    found_at: str  # ISO 8601
    tags: list[str] = Field(default_factory=list)
    source: Optional[str] = None
    site_name: Optional[str] = None


class SocialInteraction(BaseModel):
    type: str  # "post_created", "reply_sent", "friend_request"
    post_id: Optional[str] = None
    content_preview: str
    timestamp: str


class TravelSession(BaseModel):
    session_id: str
    status: TravelStatus = TravelStatus.PENDING
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    # 用户配置
    time_limit_minutes: int = 300
    credit_limit: int = 1000
    want_friends: bool = True
    friend_description: Optional[str] = None
    goal_prompt: Optional[str] = None
    post_to_forum: bool = True
    deliver_full_report: bool = True
    deliver_channel: Optional[str] = None
    deliver_to: Optional[str] = None
    # 运行时跟踪
    openclaw_session_key: Optional[str] = None
    tokens_used: int = 0
    credits_used: int = 0
    elapsed_minutes: float = 0.0
    tool_stats: dict[str, int] = Field(default_factory=dict)
    unique_sources: int = 0
    wrap_up_sent: bool = False
    idle_polls: int = 0
    # 结果
    discoveries: list[TravelDiscovery] = Field(default_factory=list)
    social_interactions: list[SocialInteraction] = Field(default_factory=list)
    summary: Optional[str] = None
    forum_digest: Optional[str] = None
    forum_post_id: Optional[str] = None
    forum_post_status: Optional[str] = None
    full_report_delivery_status: Optional[str] = None
    notification_delivery_statuses: dict[str, str] = Field(default_factory=dict)
    error: Optional[str] = None


class TravelHistoryAnalysis(BaseModel):
    discoveries: list[TravelDiscovery] = Field(default_factory=list)
    social_interactions: list[SocialInteraction] = Field(default_factory=list)
    credits_used: int = 0
    tool_stats: dict[str, int] = Field(default_factory=dict)


# ── 持久化 ──────────────────────────────────────


def _session_path(session_id: str) -> Path:
    return TRAVEL_DIR / f"{session_id}.json"


def create_session(
    agent_id: Optional[str] = None,
    time_limit_minutes: int = 300,
    credit_limit: int = 1000,
    want_friends: bool = True,
    friend_description: Optional[str] = None,
    goal_prompt: Optional[str] = None,
    post_to_forum: bool = True,
    deliver_full_report: bool = True,
    deliver_channel: Optional[str] = None,
    deliver_to: Optional[str] = None,
) -> TravelSession:
    """创建并持久化一个新的旅行 session"""
    session = TravelSession(
        session_id=uuid.uuid4().hex[:16],
        created_at=datetime.now().isoformat(),
        agent_id=agent_id,
        time_limit_minutes=time_limit_minutes,
        credit_limit=credit_limit,
        want_friends=want_friends,
        friend_description=friend_description,
        goal_prompt=goal_prompt,
        post_to_forum=post_to_forum,
        deliver_full_report=deliver_full_report,
        deliver_channel=deliver_channel,
        deliver_to=deliver_to,
    )
    save_session(session)
    logger.info(f"旅行 session 已创建: {session.session_id}")
    return session


def save_session(session: TravelSession) -> None:
    """将 session 写入 JSON 文件"""
    path = _session_path(session.session_id)
    path.write_text(session.model_dump_json(indent=2), encoding="utf-8")


def load_session(session_id: str) -> TravelSession:
    """从文件读取 session"""
    path = _session_path(session_id)
    if not path.exists():
        raise FileNotFoundError(f"旅行 session 不存在: {session_id}")
    return TravelSession.model_validate_json(path.read_text(encoding="utf-8"))


def get_active_session() -> Optional[TravelSession]:
    """找到当前 status=running 的 session（最多一个）"""
    for path in TRAVEL_DIR.glob("*.json"):
        try:
            session = TravelSession.model_validate_json(path.read_text(encoding="utf-8"))
            if session.status == TravelStatus.RUNNING:
                return session
        except Exception:
            continue
    return None


def list_sessions() -> list[TravelSession]:
    """列出所有 session，按 created_at 倒序"""
    sessions: list[TravelSession] = []
    for path in TRAVEL_DIR.glob("*.json"):
        try:
            sessions.append(TravelSession.model_validate_json(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    sessions.sort(key=lambda s: s.created_at, reverse=True)
    return sessions


# ── Prompt 构建 ─────────────────────────────────


def build_travel_prompt(session: TravelSession) -> str:
    """生成给 OpenClaw 的探索指令"""
    goal = session.goal_prompt or "自由探索互联网，优先了解最新热点、值得持续追踪的话题和高质量来源"
    agent_line = f"- 当前执行干员：{session.agent_name or session.agent_id}\n" if session.agent_id or session.agent_name else ""
    return f"""你正在执行一次长期网络探索任务，运行环境是 OpenClaw。

核心目标：
{agent_line}- 围绕这个方向探索：{goal}
- 优先获取“最新、仍在发展、值得继续追踪”的内容，而不是泛泛百科知识
- 产出结构化发现，并在预算接近上限时主动收束并准备报告

预算约束：
- 时间上限：{session.time_limit_minutes} 分钟
- 积分预算：{session.credit_limit} 积分（后端会按工具调用做近似计费）

工具策略：
1. 先用 web_search 获取最新线索、热点主题和高价值来源
2. 再用 browser 打开、导航、快照、验证页面内容
3. web_search 默认使用压缩结果；只有确实需要原始结果时才显式 raw=true
4. browser 只允许这些 action：
   status, start, profiles, tabs, open, focus, close, snapshot, screenshot, navigate, console, pdf, upload, dialog, act
5. 不要编造不存在的 browser action，例如 extract、getText

探索纪律：
- 每一轮继续探索前，都必须有明确的新信息目标
- 如果连续两次结果高度重复，停止扩搜并开始总结
- 优先保留一手来源、官方来源、原始页面，而不是反复引用二手摘要
- 如果已经掌握足够证据，直接收束，不要为了“看起来更努力”而空转

输出规则：
- 每当形成一个值得保留的发现时，追加一个 [DISCOVERY] 块：
[DISCOVERY]
url: <网页URL>
title: <标题>
summary: <一句话总结，说明它为什么重要>
tags: <标签1>, <标签2>
[/DISCOVERY]

- 阶段性总结时，简要说明：
  1. 当前热点/趋势
  2. 你最值得追踪的 3-5 个来源
  3. 接下来还缺什么信息

现在开始探索。先广搜，再聚焦高价值页面，保持节制但保留发现。"""


def build_social_prompt(session: TravelSession) -> str:
    """生成社交指令"""
    desc = session.friend_description or "任何有趣的 AI Agent"
    return f"""补充社交目标：
- 在合适的时候浏览娜迦网络论坛，与其他 AI 互动
- 你希望结识的对象：{desc}
- 只有当探索已经有阶段性成果时，再进行社交；不要让社交打断主探索任务

若有社交互动，用以下格式记录：
[SOCIAL]
type: <post_created|reply_sent|friend_request>
post_id: <帖子ID，如有>
content_preview: <互动内容预览>
[/SOCIAL]"""


def build_wrap_up_prompt(session: TravelSession) -> str:
    goal = session.goal_prompt or "自由探索最新热点"
    return f"""请停止扩展探索，开始收束并输出最终旅行报告。

报告要求：
1. 先给出本次探索的总判断，回答目标：{goal}
2. 总结 3-7 条最有价值的发现，按重要性排序
3. 每条发现尽量点出来源/页面，以及它为什么值得继续追踪
4. 说明哪些信息已经足够，哪些仍存在不确定性
5. 如果有社交互动，再单独附一段社交总结

不要再继续盲目搜索或重复访问页面，直接完成报告。"""


def _compact_text(text: Optional[str], limit: int = 220) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(1, limit - 1)] + "…"


def build_forum_post_payload(session: TravelSession) -> dict[str, Any]:
    """根据旅行结果构建论坛精华帖。"""
    title_seed = _compact_text(session.goal_prompt, 36) or "最新热点探索"
    summary = _compact_text(session.summary, 700) or "本轮探索已完成，但暂未生成完整总结。"
    top_discoveries = session.discoveries[:5]
    top_tags: list[str] = []
    for item in top_discoveries:
        for tag in item.tags:
            if tag and tag not in top_tags:
                top_tags.append(tag)
            if len(top_tags) >= 5:
                break
    lines = [
        f"【探索方向】{title_seed}",
        "",
        "【精华总结】",
        summary,
    ]
    if top_discoveries:
        lines.extend(["", "【本轮值得继续追踪】"])
        for idx, item in enumerate(top_discoveries, start=1):
            source = item.site_name or urlparse(item.url).netloc or item.url
            lines.append(
                f"{idx}. {item.title}\n"
                f"来源：{source}\n"
                f"摘要：{_compact_text(item.summary, 140)}\n"
                f"链接：{item.url}"
            )
    if session.social_interactions:
        lines.extend(["", f"【社交互动】本轮记录 {len(session.social_interactions)} 次互动"])
    content = "\n".join(lines).strip()
    return {
        "title": f"探索速报｜{title_seed}"[:60],
        "content": content[:4000],
        "tags": top_tags[:5],
        "source": "openclaw-travel",
    }


# ── 结果解析 ─────────────────────────────────────


def _clean_wrapped_text(text: str) -> str:
    if not text:
        return ""

    def _replace(match: re.Match[str]) -> str:
        return match.group("body")

    text = WRAPPED_CONTENT_RE.sub(_replace, text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_maybe_serialized(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        return ast.literal_eval(text)
    except Exception:
        return value


def _extract_text_items(payload: Any) -> list[str]:
    payload = _parse_maybe_serialized(payload)
    texts: list[str] = []
    if isinstance(payload, dict):
        content = payload.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        texts.append(_clean_wrapped_text(text))
        result = payload.get("result")
        if result is not None and result is not payload:
            texts.extend(_extract_text_items(result))
    elif isinstance(payload, list):
        for item in payload:
            texts.extend(_extract_text_items(item))
    elif isinstance(payload, str) and payload.strip():
        texts.append(_clean_wrapped_text(payload))
    return [text for text in texts if text]


def _guess_title_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.netloc or url
        path = parsed.path.rstrip("/").split("/")[-1]
        if path:
            return f"{host} / {path}"
        return host
    except Exception:
        return url


def _safe_summary(text: str, max_len: int = 220) -> str:
    text = _clean_wrapped_text(text)
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 1].rstrip()}…"


def _discovery_from_search_item(item: dict[str, Any], *, query: str, now: str) -> Optional[TravelDiscovery]:
    url = str(item.get("url") or "").strip()
    if not url:
        return None

    title = _clean_wrapped_text(str(item.get("title") or "").strip()) or _guess_title_from_url(url)
    summary = (
        _clean_wrapped_text(str(item.get("description") or "").strip())
        or _clean_wrapped_text(str(item.get("snippet") or "").strip())
        or f"搜索命中：{query}"
    )
    site_name = str(item.get("siteName") or item.get("site_name") or "").strip() or None
    tags = ["web_search"]
    if site_name:
        tags.append(site_name)
    return TravelDiscovery(
        url=url,
        title=_safe_summary(title, 120),
        summary=_safe_summary(summary),
        found_at=now,
        tags=tags,
        source="web_search",
        site_name=site_name,
    )


def _discoveries_from_web_search_result(result: Any, now: str) -> list[TravelDiscovery]:
    payload = _parse_maybe_serialized(result)
    if not isinstance(payload, dict):
        return []
    value = payload.get("value", payload)
    if not isinstance(value, dict):
        return []

    query = str(value.get("query") or "").strip() or "未命名搜索"
    discoveries: list[TravelDiscovery] = []
    for item in value.get("results", [])[:5]:
        if not isinstance(item, dict):
            continue
        discovery = _discovery_from_search_item(item, query=query, now=now)
        if discovery is not None:
            discoveries.append(discovery)
    return discoveries


def _discovery_from_browser_result(args: dict[str, Any], result: Any, now: str) -> Optional[TravelDiscovery]:
    payload = _parse_maybe_serialized(result)
    details = payload.get("details", {}) if isinstance(payload, dict) else {}
    if not isinstance(details, dict):
        details = {}

    url = str(details.get("url") or "").strip()
    if not url:
        return None

    action = str(args.get("action") or "browser").strip() or "browser"
    text_parts = _extract_text_items(payload)
    summary = text_parts[0] if text_parts else f"通过 browser.{action} 访问并检查页面"
    title = str(details.get("title") or "").strip() or _guess_title_from_url(url)
    tags = ["browser", action]
    site_name = urlparse(url).netloc or None
    if site_name:
        tags.append(site_name)
    return TravelDiscovery(
        url=url,
        title=_safe_summary(title, 120),
        summary=_safe_summary(summary),
        found_at=now,
        tags=tags,
        source="browser",
        site_name=site_name,
    )


def _estimate_event_cost(name: str, args: dict[str, Any], is_error: bool) -> tuple[str, int]:
    if name == "browser":
        action = str(args.get("action") or "").strip() or "unknown"
        cost = BROWSER_ACTION_COSTS.get(action, TOOL_BASE_COSTS["browser"])
        return f"browser.{action}", max(1, cost if not is_error else max(1, cost // 2))

    cost = TOOL_BASE_COSTS.get(name, 6)
    return name, max(1, cost if not is_error else max(1, cost // 2))


def analyze_history(history_messages: list[dict]) -> TravelHistoryAnalysis:
    """从 OpenClaw 历史中提炼发现、社交互动和近似预算消耗。"""
    now = datetime.now().isoformat()
    analysis = TravelHistoryAnalysis()
    seen_urls: set[str] = set()
    seen_tool_results: set[str] = set()
    call_args: dict[str, dict[str, Any]] = {}

    for msg in history_messages:
        content = msg.get("content", "")
        if isinstance(content, str) and content:
            for match in DISCOVERY_TAG_RE.finditer(content):
                tags_str = match.group("tags") or ""
                tags = [t.strip() for t in tags_str.split(",") if t.strip()]
                url = match.group("url").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                analysis.discoveries.append(
                    TravelDiscovery(
                        url=url,
                        title=match.group("title").strip(),
                        summary=match.group("summary").strip(),
                        found_at=now,
                        tags=tags,
                        source="assistant",
                    )
                )

        tool_events = msg.get("toolEvents") or msg.get("tool_events") or []
        if not isinstance(tool_events, list):
            continue

        for event in tool_events:
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("type") or "").strip()
            tool_call_id = str(event.get("toolCallId") or "").strip()
            if event_type == "tool_call" and tool_call_id:
                args = event.get("args")
                if isinstance(args, dict):
                    call_args[tool_call_id] = args
                else:
                    parsed = _parse_maybe_serialized(args)
                    call_args[tool_call_id] = parsed if isinstance(parsed, dict) else {}
                continue

            if event_type != "tool_result" or not tool_call_id or tool_call_id in seen_tool_results:
                continue

            seen_tool_results.add(tool_call_id)
            name = str(event.get("name") or "").strip()
            args = call_args.get(tool_call_id, {})
            is_error = bool(event.get("isError"))
            stat_key, cost = _estimate_event_cost(name, args, is_error)
            analysis.credits_used += cost
            analysis.tool_stats[stat_key] = analysis.tool_stats.get(stat_key, 0) + 1

            if is_error:
                continue

            result = event.get("result")
            if name == "web_search":
                for discovery in _discoveries_from_web_search_result(result, now):
                    if discovery.url in seen_urls:
                        continue
                    seen_urls.add(discovery.url)
                    analysis.discoveries.append(discovery)
                continue

            if name == "browser":
                discovery = _discovery_from_browser_result(args, result, now)
                if discovery is not None and discovery.url not in seen_urls:
                    seen_urls.add(discovery.url)
                    analysis.discoveries.append(discovery)

    analysis.social_interactions = parse_social(history_messages)
    return analysis


def parse_discoveries(history_messages: list[dict]) -> list[TravelDiscovery]:
    """从 OpenClaw 回复和工具结果中提炼发现。"""
    return analyze_history(history_messages).discoveries


def estimate_travel_credits(history_messages: list[dict]) -> tuple[int, dict[str, int]]:
    analysis = analyze_history(history_messages)
    return analysis.credits_used, analysis.tool_stats


def parse_social(history_messages: list[dict]) -> list[SocialInteraction]:
    """解析 [SOCIAL]...[/SOCIAL] 格式"""
    interactions: list[SocialInteraction] = []
    now = datetime.now().isoformat()
    for msg in history_messages:
        content = msg.get("content", "")
        if not content:
            continue
        for match in SOCIAL_TAG_RE.finditer(content):
            post_id = match.group("post_id")
            if post_id:
                post_id = post_id.strip()
                if post_id.lower() in ("none", "null", ""):
                    post_id = None
            interactions.append(
                SocialInteraction(
                    type=match.group("type").strip(),
                    post_id=post_id,
                    content_preview=match.group("content_preview").strip(),
                    timestamp=now,
                )
            )
    return interactions
