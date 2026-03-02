#!/usr/bin/env python3
"""
Agentic Tool Loop 核心引擎
实现单LLM agentic loop：模型在对话中发起工具调用，接收结果，再继续推理，直到不再需要工具。
"""

import asyncio
import json
import logging
import re
import time as _time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx

from system.config import get_config, get_server_port

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 解析工具
# ---------------------------------------------------------------------------


def _normalize_fullwidth_json_chars(text: str) -> str:
    """将常见全角JSON相关字符归一化为ASCII"""
    if not text:
        return text
    translation_table = str.maketrans(
        {
            "｛": "{",
            "｝": "}",
            "：": ":",
            "，": ",",
            "\u201c": '"',
            "\u201d": '"',
            "\u2018": "'",
            "\u2019": "'",
        }
    )
    return text.translate(translation_table)


def _extract_json_objects(text: str) -> List[Dict[str, Any]]:
    """从文本中提取所有顶层JSON对象（花括号深度匹配 + json5/json 解析 + agentType过滤）"""

    def _loads(s: str) -> Any:
        try:
            import json5 as _json5

            return _json5.loads(s)
        except Exception:
            return json.loads(s)

    objects: List[Dict[str, Any]] = []
    start: Optional[int] = None
    depth = 0

    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    candidate = text[start : i + 1].strip()
                    start = None
                    if candidate in ("{}", "{ }"):
                        continue
                    try:
                        parsed = _loads(candidate)
                    except Exception:
                        continue
                    if isinstance(parsed, dict):
                        objects.append(parsed)
                    elif isinstance(parsed, list):
                        for item in parsed:
                            if isinstance(item, dict):
                                objects.append(item)

    # 只保留含 agentType 字段的对象
    return [obj for obj in objects if isinstance(obj.get("agentType"), str) and obj["agentType"]]


def _extract_tool_blocks(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """从 ```tool``` 代码块中提取工具调用JSON。

    Returns:
        (clean_text, tool_calls) — clean_text 是移除代码块后的纯文本
    """

    tool_calls: List[Dict[str, Any]] = []
    # 匹配 ```tool ... ``` 代码块（允许未闭合的尾部块用 \Z 兜底）
    # 注意: 用 [ \t]* 而非 \s* 避免吃掉换行符; 用 \Z 而非 $ 避免 MULTILINE 下提前匹配行尾
    pattern = re.compile(r"```tool[ \t]*\n([\s\S]*?)(?:```|\Z)")

    for match in pattern.finditer(text):
        block_content = match.group(1).strip()
        if not block_content:
            continue
        normalized = _normalize_fullwidth_json_chars(block_content)
        extracted = _extract_json_objects(normalized)
        tool_calls.extend(extracted)

    # 从文本中移除 ```tool...``` 代码块
    clean_text = pattern.sub("", text).strip()
    # 清理多余空行
    clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)
    return clean_text, tool_calls


def parse_tool_calls_from_text(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """从LLM完整输出中提取所有工具调用JSON。

    优先从 ```tool``` 代码块提取，回退到裸JSON行提取（向后兼容）。

    Returns:
        (clean_text, tool_calls) — clean_text 是去掉工具调用后的纯文本
    """
    # 优先使用 ```tool``` 代码块
    clean_text, tool_calls = _extract_tool_blocks(text)
    if tool_calls:
        return clean_text, tool_calls

    # 回退：从裸文本中提取含 agentType 的JSON对象（向后兼容）
    normalized = _normalize_fullwidth_json_chars(text)
    tool_calls = _extract_json_objects(normalized)

    if not tool_calls:
        return text, []

    # 从原始文本中移除工具调用JSON所在的行
    clean_lines = []
    for line in text.split("\n"):
        norm_line = _normalize_fullwidth_json_chars(line.strip())
        if norm_line:
            extracted = _extract_json_objects(norm_line)
            if extracted:
                continue  # 跳过包含工具调用的行
        clean_lines.append(line)

    clean_text = "\n".join(clean_lines).strip()
    return clean_text, tool_calls


# ---------------------------------------------------------------------------
# OpenClaw 共享客户端与可用性预检
# ---------------------------------------------------------------------------

_shared_openclaw_client: Optional[httpx.AsyncClient] = None


def _get_openclaw_client() -> httpx.AsyncClient:
    """获取或创建共享的 httpx 客户端（避免每次调用都新建连接）"""
    global _shared_openclaw_client
    if _shared_openclaw_client is None or _shared_openclaw_client.is_closed:
        _shared_openclaw_client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout=150.0, connect=10.0),
            proxy=None,  # localhost 请求不走系统代理
        )
    return _shared_openclaw_client


_openclaw_available: Optional[bool] = None
_openclaw_check_time: float = 0.0
_OPENCLAW_CHECK_TTL = 30.0
_openclaw_start_attempted: bool = False  # 每次进程生命周期内只自动启动一次


async def _check_openclaw_available() -> bool:
    """检查 OpenClaw 服务是否可用，不可用时尝试自动启动"""
    global _openclaw_available, _openclaw_check_time, _openclaw_start_attempted
    now = _time.monotonic()
    if _openclaw_available is not None and (now - _openclaw_check_time) < _OPENCLAW_CHECK_TTL:
        return _openclaw_available

    agent_base = f"http://localhost:{get_server_port('agent_server')}"
    client = _get_openclaw_client()

    _openclaw_available = await _probe_openclaw_health(client, agent_base)

    # 不可用且还没尝试过自动启动 → 启动一次
    if not _openclaw_available and not _openclaw_start_attempted:
        _openclaw_start_attempted = True
        logger.info("[AgenticLoop] OpenClaw gateway 不可用，尝试自动启动...")
        try:
            resp = await client.post(f"{agent_base}/openclaw/gateway/start", timeout=45.0)
            if resp.status_code == 200:
                start_result = resp.json()
                # start_gateway 内部已经等待并检查了连通性
                if start_result.get("success"):
                    logger.info("[AgenticLoop] OpenClaw gateway 启动成功")
                    # 再确认一次 health
                    _openclaw_available = await _probe_openclaw_health(client, agent_base)
                    if not _openclaw_available:
                        # start 说成功但 health 还没好，短暂等待
                        await asyncio.sleep(2)
                        _openclaw_available = await _probe_openclaw_health(client, agent_base)
                else:
                    msg = start_result.get("message", "未知原因")
                    logger.warning(f"[AgenticLoop] OpenClaw gateway 启动失败: {msg}")
            else:
                logger.warning(f"[AgenticLoop] OpenClaw gateway 启动请求失败: HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"[AgenticLoop] OpenClaw gateway 自动启动异常: {e}")

    _openclaw_check_time = _time.monotonic()
    return _openclaw_available


async def _probe_openclaw_health(client: httpx.AsyncClient, agent_base: str) -> bool:
    """探测 OpenClaw gateway 是否健康"""
    try:
        resp = await client.get(f"{agent_base}/openclaw/health", timeout=3.0)
        data = resp.json()
        return (
            resp.status_code == 200
            and data.get("success", False)
            and data.get("health", {}).get("status") == "healthy"
        )
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 工具执行
# ---------------------------------------------------------------------------


async def _execute_mcp_call(call: Dict[str, Any]) -> Dict[str, Any]:
    """执行单个MCP调用"""
    service_name = call.get("service_name", "")
    tool_name = call.get("tool_name", "")

    if not service_name and tool_name in {
        "ask_guide",
        "ask_guide_with_screenshot",
        "calculate_damage",
        "get_team_recommendation",
    }:
        service_name = "game_guide"
        call["service_name"] = service_name

    # 游戏攻略功能仅登录用户可用
    if service_name == "game_guide":
        from apiserver import naga_auth

        if not naga_auth.is_authenticated():
            return {
                "tool_call": call,
                "result": "游戏攻略功能需要登录 Naga 账号后才能使用，请先登录。",
                "status": "error",
                "service_name": service_name,
                "tool_name": tool_name,
            }

    try:
        from mcpserver.mcp_manager import get_mcp_manager

        manager = get_mcp_manager()
        t0 = _time.monotonic()
        result = await manager.unified_call(service_name, call)
        elapsed = _time.monotonic() - t0
        logger.info(f"[AgenticLoop] MCP调用完成: {service_name}/{tool_name} 耗时 {elapsed:.2f}s")
        return {
            "tool_call": call,
            "result": result,
            "status": "success",
            "service_name": service_name,
            "tool_name": tool_name,
        }
    except Exception as e:
        logger.error(f"[AgenticLoop] MCP调用失败: service={service_name}, error={e}")
        return {
            "tool_call": call,
            "result": f"调用失败: {e}",
            "status": "error",
            "service_name": service_name,
            "tool_name": tool_name,
        }


async def _execute_openclaw_call(call: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    """执行单个OpenClaw调用（Agent 模式，通过 /hooks/agent 走二次 LLM）"""
    message = call.get("message", "")
    task_type = call.get("task_type", "message")

    if not message:
        return {
            "tool_call": call,
            "result": "缺少message字段",
            "status": "error",
            "service_name": "openclaw",
            "tool_name": task_type,
        }

    if not await _check_openclaw_available():
        return {
            "tool_call": call,
            "result": "OpenClaw 服务当前不可用，请稍后重试",
            "status": "error",
            "service_name": "openclaw",
            "tool_name": task_type,
        }

    payload = {
        "message": message,
        "session_key": call.get("session_key", f"naga_{session_id}"),
        "name": "Naga",
        "wake_mode": "now",
        "timeout_seconds": 120,
    }

    if task_type == "cron" and call.get("schedule"):
        payload["message"] = f"[定时任务 cron: {call.get('schedule')}] {message}"
    elif task_type == "reminder" and call.get("at"):
        payload["message"] = f"[提醒 在 {call.get('at')} 后] {message}"

    try:
        client = _get_openclaw_client()
        response = await client.post(
            f"http://localhost:{get_server_port('agent_server')}/openclaw/send",
            json=payload,
        )
        if response.status_code == 200:
            result_data = response.json()
            # 先检查 agent_server 返回的 success 标记
            if not result_data.get("success", True):
                error_msg = result_data.get("error") or "OpenClaw任务执行失败"
                return {
                    "tool_call": call,
                    "result": f"联网搜索失败: {error_msg}",
                    "status": "error",
                    "service_name": "openclaw",
                    "tool_name": task_type,
                }
            # agent_server 返回两个字段：replies(列表，异步轮询时填充) 和 reply(字符串，同步完成时填充)
            replies = result_data.get("replies") or []
            if replies:
                combined = "\n".join(replies)
            elif result_data.get("reply"):
                combined = result_data["reply"]
            else:
                combined = "任务已提交，暂无返回结果"
            return {
                "tool_call": call,
                "result": combined,
                "status": "success",
                "service_name": "openclaw",
                "tool_name": task_type,
            }
        else:
            return {
                "tool_call": call,
                "result": f"HTTP {response.status_code}: {response.text[:200]}",
                "status": "error",
                "service_name": "openclaw",
                "tool_name": task_type,
            }
    except Exception as e:
        logger.error(f"[AgenticLoop] OpenClaw调用失败: {e}")
        return {
            "tool_call": call,
            "result": f"调用失败: {e}",
            "status": "error",
            "service_name": "openclaw",
            "tool_name": task_type,
        }


async def _execute_openclaw_tool_call(call: Dict[str, Any]) -> Dict[str, Any]:
    """直接调用 OpenClaw 工具，跳过 Agent LLM（通过 /tools/invoke）"""
    tool_name = call.get("tool_name", "")
    tool_args = call.get("args", {})

    if not tool_name:
        return {
            "tool_call": call, "result": "缺少 tool_name",
            "status": "error", "service_name": "openclaw_tool", "tool_name": "unknown",
        }

    if not await _check_openclaw_available():
        return {
            "tool_call": call, "result": "OpenClaw 服务当前不可用，请稍后重试",
            "status": "error", "service_name": "openclaw_tool", "tool_name": tool_name,
        }

    try:
        client = _get_openclaw_client()
        t0 = _time.monotonic()
        response = await client.post(
            f"http://localhost:{get_server_port('agent_server')}/openclaw/tools/invoke",
            json={"tool": tool_name, "args": tool_args},
        )
        elapsed = _time.monotonic() - t0
        if response.status_code == 200:
            result_data = response.json()
            # 先检查 agent_server 层面的 success 标记（如 tool_not_found）
            if not result_data.get("success", True):
                error_msg = result_data.get("error") or result_data.get("detail") or "工具调用失败"
                logger.error(f"[AgenticLoop] OpenClaw工具返回失败: {tool_name}, error={error_msg}")
                return {
                    "tool_call": call, "result": f"调用失败: {error_msg}",
                    "status": "error", "service_name": "openclaw_tool", "tool_name": tool_name,
                }
            # agent_server 返回 { success: true, result: { ok, result: { content: [...] } } }
            # invoke_tool 包了一层，需解开两层 result 才能到 OpenClaw 的原始工具输出
            result_content = result_data.get("result", result_data)
            if isinstance(result_content, dict) and "result" in result_content:
                result_content = result_content["result"]

            # 检查 OpenClaw 工具级别的错误（isError 标记 或 error 字段）
            if isinstance(result_content, dict) and (result_content.get("isError") or "error" in result_content):
                readable = _extract_openclaw_tool_result(result_content)
                logger.error(f"[AgenticLoop] OpenClaw工具错误: {tool_name}, result={readable[:300]}")
                return {
                    "tool_call": call, "result": f"工具执行错误: {readable}",
                    "status": "error", "service_name": "openclaw_tool", "tool_name": tool_name,
                }

            readable = _extract_openclaw_tool_result(result_content)

            # 检测嵌套在 content text 中的 JSON 错误（如 {"error": "missing_brave_api_key", ...}）
            if readable.lstrip().startswith("{"):
                try:
                    parsed = json.loads(readable)
                    if isinstance(parsed, dict) and "error" in parsed:
                        error_msg = parsed.get("message") or str(parsed["error"])
                        logger.error(f"[AgenticLoop] OpenClaw工具错误: {tool_name}, error={error_msg}")
                        return {
                            "tool_call": call, "result": f"工具执行错误: {error_msg}",
                            "status": "error", "service_name": "openclaw_tool", "tool_name": tool_name,
                        }
                except (json.JSONDecodeError, TypeError):
                    pass

            logger.info(f"[AgenticLoop] OpenClaw直接工具调用完成: {tool_name} 耗时 {elapsed:.2f}s, 结果长度={len(readable)}")
            logger.info(f"[AgenticLoop] OpenClaw工具结果预览: {readable[:300]}")
            return {
                "tool_call": call, "result": readable,
                "status": "success", "service_name": "openclaw_tool", "tool_name": tool_name,
            }
        else:
            logger.error(f"[AgenticLoop] OpenClaw直接工具调用HTTP错误: {tool_name}, status={response.status_code}, body={response.text[:200]}")
            return {
                "tool_call": call, "result": f"调用失败: HTTP {response.status_code} - {response.text[:200]}",
                "status": "error", "service_name": "openclaw_tool", "tool_name": tool_name,
            }
    except Exception as e:
        logger.error(f"[AgenticLoop] OpenClaw直接工具调用失败: {tool_name}, error={e}")
        return {
            "tool_call": call, "result": f"调用异常: {e}",
            "status": "error", "service_name": "openclaw_tool", "tool_name": tool_name,
        }


def _extract_openclaw_tool_result(result: Any) -> str:
    """从 OpenClaw /tools/invoke 返回值中提取可读文本"""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        # 标准格式: { content: [{ type: "text", text: "..." }] }
        content = result.get("content", [])
        if isinstance(content, list) and content:
            texts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        texts.append(item.get("text", ""))
                    elif "text" in item:
                        texts.append(str(item["text"]))
                elif isinstance(item, str):
                    texts.append(item)
            if texts:
                return "\n".join(texts)
        # 备选: 直接有 text 字段
        if "text" in result:
            return str(result["text"])
        # 备选: 有 error/message 字段（OpenClaw 错误响应）
        if "error" in result:
            return f"错误: {result['error']}"
        if "message" in result:
            return str(result["message"])
        # 兜底: JSON dump
        return json.dumps(result, ensure_ascii=False)
    if isinstance(result, list):
        # 直接是 content 数组
        texts = []
        for item in result:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
            elif isinstance(item, str):
                texts.append(item)
        return "\n".join(texts) if texts else json.dumps(result, ensure_ascii=False)
    return str(result)


async def _execute_naga_control(call: Dict[str, Any]) -> Dict[str, Any]:
    """执行 Naga 自身控制操作（直接调用，无需 HTTP）"""
    from .naga_control import execute

    action = call.get("action", "")
    params = call.get("params", {})

    t0 = _time.monotonic()
    result = await execute(action, params)
    elapsed = _time.monotonic() - t0
    logger.info(f"[AgenticLoop] NagaControl 完成: {action} 耗时 {elapsed:.2f}s")

    return {
        "tool_call": call,
        "result": json.dumps(result, ensure_ascii=False),
        "status": "success" if result.get("success") else "error",
        "service_name": "naga_control",
        "tool_name": action,
    }


async def _send_live2d_actions(live2d_calls: List[Dict[str, Any]], session_id: str):
    """Fire-and-forget发送Live2D动作到UI"""

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout=5.0)) as client:
            for call in live2d_calls:
                action_name = call.get("action", "")
                logger.info(f"[AgenticLoop] 发送 Live2D 动作: {action_name}, 完整调用: {call}")
                if not action_name:
                    continue
                payload = {
                    "session_id": session_id,
                    "action": "live2d_action",
                    "action_name": action_name,
                }
                try:
                    await client.post(
                        f"http://localhost:{get_server_port('api_server')}/ui_notification",
                        json=payload,
                    )
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"[AgenticLoop] Live2D动作发送失败: {e}")


async def execute_tool_calls(tool_calls: List[Dict[str, Any]], session_id: str) -> List[Dict[str, Any]]:
    """按 agentType 分组并行执行工具调用（不包含 live2d）。

    Returns:
        [{"tool_call": {...}, "result": "...", "status": "success|error", "service_name": "...", "tool_name": "..."}]
    """
    tasks = []
    for call in tool_calls:
        agent_type = call.get("agentType", "")
        if agent_type == "mcp":
            tasks.append(_execute_mcp_call(call))
        elif agent_type == "openclaw":
            tasks.append(_execute_openclaw_call(call, session_id))
        elif agent_type == "openclaw_tool":
            tasks.append(_execute_openclaw_tool_call(call))
        elif agent_type == "naga_control":
            tasks.append(_execute_naga_control(call))
        else:
            logger.warning(f"[AgenticLoop] 未知agentType: {agent_type}, 跳过: {call}")

    if not tasks:
        return []

    results = await asyncio.gather(*tasks, return_exceptions=True)
    final = []
    for r in results:
        if isinstance(r, Exception):
            final.append(
                {
                    "tool_call": {},
                    "result": f"执行异常: {r}",
                    "status": "error",
                    "service_name": "unknown",
                    "tool_name": "unknown",
                }
            )
        else:
            final.append(r)
    return final


# ---------------------------------------------------------------------------
# 格式化
# ---------------------------------------------------------------------------


def format_tool_results_for_llm(results: List[Dict[str, Any]]) -> str:
    """将工具执行结果格式化为LLM可理解的文本"""
    parts = []
    total = len(results)
    for idx, r in enumerate(results, 1):
        svc = r.get("service_name", "unknown")
        tool = r.get("tool_name", "")
        status = r.get("status", "unknown")
        result_text = r.get("result", "")
        label = f"{svc}"
        if tool:
            label += f": {tool}"
        parts.append(f"[工具结果 {idx}/{total} - {label} ({status})]\n{result_text}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# SSE 辅助
# ---------------------------------------------------------------------------


def _format_sse_event(event_type: str, data: Any) -> str:
    """格式化扩展SSE事件"""
    payload = {"type": event_type}
    if isinstance(data, dict):
        payload.update(data)
    else:
        payload["data"] = data
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
# Agentic Loop 核心
# ---------------------------------------------------------------------------


async def run_agentic_loop(
    messages: List[Dict[str, Any]],
    session_id: str,
    max_rounds: int = 5,
    model_override: Optional[Dict[str, str]] = None,
) -> AsyncGenerator[str, None]:
    """Agentic tool loop 核心。

    流式输出SSE chunks，包含：
    - content/reasoning chunks（透传自LLM）
    - round_start/tool_calls/tool_results/round_end 事件

    每一轮的content都会完整流式输出（供TTS使用），工具内容不混入content流。

    Args:
        messages: 完整的对话消息列表（含system prompt）
        session_id: 会话ID
        max_rounds: 最大循环轮数
        model_override: 临时模型覆盖参数（用于视觉模型等场景）

    Yields:
        SSE格式的data chunks
    """
    from .llm_service import get_llm_service

    llm_service = get_llm_service()

    consecutive_failures = 0  # 连续全部失败的轮次计数
    needs_summary = False  # 是否需要进行最终总结轮
    t_loop_start = _time.monotonic()

    for round_num in range(1, max_rounds + 1):
        t_round_start = _time.monotonic()
        # 0. 上下文压缩：每轮开始前检查 token 是否超限
        #    round 1 压缩历史对话，round 2+ 压缩上一轮工具结果膨胀的上下文
        try:
            from .context_compressor import compress_context
            compress_result = await compress_context(messages)
            if compress_result.compressed:
                messages[:] = compress_result.messages
            for sse_event in compress_result.sse_events:
                yield sse_event
        except Exception as e:
            logger.debug(f"[AgenticLoop] 上下文压缩跳过: {e}")

        # 1. 通知前端开始新一轮
        if round_num > 1:
            yield _format_sse_event("round_start", {"round": round_num})

        # 2. 流式调用LLM，累积完整输出
        complete_text = ""
        complete_reasoning = ""
        t_llm_start = _time.monotonic()

        async for chunk in llm_service.stream_chat_with_context(messages, get_config().api.temperature,
                                                                 model_override=model_override):
            if chunk.startswith("data: "):
                try:
                    data_str = chunk[6:].strip()
                    if data_str and data_str != "[DONE]":
                        chunk_data = json.loads(data_str)
                        chunk_type = chunk_data.get("type", "content")
                        chunk_text = chunk_data.get("text", "")

                        if chunk_type == "content":
                            complete_text += chunk_text
                        elif chunk_type == "reasoning":
                            complete_reasoning += chunk_text
                except Exception:
                    pass

            # 透传所有SSE chunks给前端（content + reasoning）
            yield chunk

        # 3. 从完整输出中解析工具调用
        t_llm_elapsed = _time.monotonic() - t_llm_start
        logger.info(
            f"[AgenticLoop] Round {round_num} LLM流式输出完成: {t_llm_elapsed:.2f}s, "
            f"content={len(complete_text)}字, reasoning={len(complete_reasoning)}字"
        )
        logger.debug(
            f"[AgenticLoop] Round {round_num} complete_text ({len(complete_text)} chars): {complete_text[:300]!r}"
        )
        clean_text, tool_calls = parse_tool_calls_from_text(complete_text)

        # 4. 分离live2d和可执行调用
        actionable_calls = [tc for tc in tool_calls if tc.get("agentType") != "live2d"]
        live2d_calls = [tc for tc in tool_calls if tc.get("agentType") == "live2d"]

        # 4a. fire-and-forget Live2D
        if live2d_calls:
            asyncio.create_task(_send_live2d_actions(live2d_calls, session_id))

        # 4b. 如果检测到了任何工具调用，发送 content_clean 让前端替换掉带有工具代码块的原文
        if tool_calls and clean_text != complete_text:
            # 保留工具调用前的简短说明文字（如"让我查一下"），仅移除 ```tool``` 代码块
            yield _format_sse_event("content_clean", {"text": clean_text})

        # 5. 如果没有可执行的工具调用，循环结束
        if not actionable_calls:
            t_round_elapsed = _time.monotonic() - t_round_start
            t_total_elapsed = _time.monotonic() - t_loop_start
            logger.info(f"[AgenticLoop] Round {round_num}: 无工具调用，循环结束 "
                        f"(本轮 {t_round_elapsed:.2f}s, 总计 {t_total_elapsed:.2f}s)")
            # 发送本轮结束信号
            yield _format_sse_event("round_end", {"round": round_num, "has_more": False})
            break

        logger.info(f"[AgenticLoop] Round {round_num}: 检测到 {len(actionable_calls)} 个工具调用")

        # 6. 通知前端正在执行工具
        call_descriptions = []
        for tc in actionable_calls:
            desc = {"agentType": tc.get("agentType", "")}
            if tc.get("service_name"):
                desc["service_name"] = tc["service_name"]
            if tc.get("tool_name"):
                desc["tool_name"] = tc["tool_name"]
            if tc.get("message"):
                desc["message"] = tc["message"][:100]
            call_descriptions.append(desc)
        yield _format_sse_event("tool_calls", {"calls": call_descriptions})

        # 7. 并行执行工具调用
        t_tool_start = _time.monotonic()
        results = await execute_tool_calls(actionable_calls, session_id)
        t_tool_elapsed = _time.monotonic() - t_tool_start
        logger.info(f"[AgenticLoop] Round {round_num}: 工具执行完成 {t_tool_elapsed:.2f}s "
                    f"({len(results)} 个工具)")

        # 7a. 检测连续失败：本轮所有工具是否全部失败
        all_failed = all(r.get("status") == "error" for r in results)
        if all_failed:
            consecutive_failures += 1
            logger.warning(f"[AgenticLoop] Round {round_num}: 本轮所有工具调用失败 (连续 {consecutive_failures} 轮)")
        else:
            consecutive_failures = 0

        # 8. 通知前端工具结果
        result_summaries = []
        for r in results:
            result_text = r.get("result", "")
            # 截断过长的结果用于前端显示
            display_result = result_text[:500] + "..." if len(result_text) > 500 else result_text
            result_summaries.append(
                {
                    "service_name": r.get("service_name", "unknown"),
                    "tool_name": r.get("tool_name", ""),
                    "status": r.get("status", "unknown"),
                    "result": display_result,
                }
            )
        yield _format_sse_event("tool_results", {"results": result_summaries})

        # 9. 将本轮LLM输出 + 工具结果注入消息历史
        #    保留工具调用前的简短说明文字，如果没有则用占位符
        assistant_content = clean_text if clean_text else "(工具调用中)"
        messages.append({"role": "assistant", "content": assistant_content})
        tool_result_text = format_tool_results_for_llm(results)
        messages.append({"role": "user", "content": tool_result_text})

        # ★ 消息队列注入：在工具执行完毕、下一轮 LLM 调用前，注入排队消息
        try:
            from .message_queue import get_message_queue
            mq = get_message_queue()
            queued = mq.drain()
            if queued:
                for qm in queued:
                    tag = f"[{qm.source}]" if qm.source != "user" else ""
                    inject_content = f"{tag} {qm.content}".strip()
                    messages.append({"role": "user", "content": inject_content})
                logger.info(
                    f"[AgenticLoop] 注入 {len(queued)} 条排队消息: "
                    f"{[q.source for q in queued]}"
                )
                yield _format_sse_event(
                    "queued_messages",
                    {"count": len(queued), "sources": [q.source for q in queued]},
                )
        except Exception as e:
            logger.debug(f"[AgenticLoop] 消息队列注入跳过: {e}")

        # 9a. 连续失败达到阈值时提前终止，进入总结轮
        if consecutive_failures >= 2:
            logger.warning(f"[AgenticLoop] 连续 {consecutive_failures} 轮工具全部失败，提前终止循环")
            yield _format_sse_event("round_end", {"round": round_num, "has_more": True})
            needs_summary = True
            break

        # 发送本轮结束信号
        yield _format_sse_event("round_end", {"round": round_num, "has_more": True})

        t_round_elapsed = _time.monotonic() - t_round_start
        t_total_elapsed = _time.monotonic() - t_loop_start
        logger.info(f"[AgenticLoop] Round {round_num}: 本轮完成 {t_round_elapsed:.2f}s "
                    f"(LLM={t_llm_elapsed:.2f}s + 工具={t_tool_elapsed:.2f}s), "
                    f"总计 {t_total_elapsed:.2f}s，继续下一轮")

    else:
        # max_rounds 用尽
        needs_summary = True

    # 最终总结轮：强制 LLM 基于已有工具结果生成回复，不再允许工具调用
    if needs_summary:
        logger.warning(f"[AgenticLoop] 执行最终总结轮")

        # 总结轮前也检查压缩（多轮工具调用后 context 可能已经很大）
        try:
            from .context_compressor import compress_context
            compress_result = await compress_context(messages)
            if compress_result.compressed:
                messages[:] = compress_result.messages
            for sse_event in compress_result.sse_events:
                yield sse_event
        except Exception as e:
            logger.debug(f"[AgenticLoop] 总结轮压缩跳过: {e}")

        # 通知前端开始总结轮（重要：触发 api_server 重置 is_tool_event 标记）
        yield _format_sse_event("round_start", {"round": max_rounds + 1, "summary": True})

        # 注入总结指令
        messages.append({
            "role": "user",
            "content": (
                "[系统提示] 工具调用轮次已用尽。请根据以上所有工具返回结果，直接回答用户的问题。"
                "如果所有工具都失败了，请诚实告知用户当前无法完成该操作，并给出建议。"
                "不要再发起任何工具调用。"
            ),
        })

        # 最终总结轮：流式输出
        async for chunk in llm_service.stream_chat_with_context(messages, get_config().api.temperature,
                                                                 model_override=model_override):
            yield chunk

        yield _format_sse_event("round_end", {"round": max_rounds + 1, "has_more": False})
