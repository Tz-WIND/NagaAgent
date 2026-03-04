"""核心对话路由（/chat, /chat/stream）"""

import asyncio
import logging
import threading
import traceback
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from system.config import get_config, build_system_prompt, build_context_supplement
from apiserver import naga_auth
from apiserver.message_manager import message_manager
from apiserver.llm_service import get_llm_service
from apiserver.response_util import extract_message
from apiserver.api_server import (
    ChatRequest,
    ChatResponse,
    _vlm_sessions,
    _save_conversation_and_logs,
    _notify_conversation_event,
    _is_voice_runtime_paused,
)
from apiserver.routes.tools import _update_proactive_activity_silent

logger = logging.getLogger(__name__)

router = APIRouter()


# ============ 内部辅助函数 ============


async def _trigger_chat_stream_no_intent(session_id: str, response_text: str):
    """触发聊天流式响应但不触发意图分析 - 发送纯粹的AI回复到UI"""
    try:
        logger.info(f"[UI发送] 开始发送AI回复到UI，会话: {session_id}")
        logger.info(f"[UI发送] 发送内容: {response_text[:200]}...")

        # 直接调用现有的流式对话接口，但跳过意图分析
        import httpx

        # 构建请求数据 - 使用纯粹的AI回复内容，并跳过意图分析
        chat_request = {
            "message": response_text,  # 直接使用AI回复内容，不加标记
            "stream": True,
            "session_id": session_id,
            "disable_tts": False,
            "return_audio": False,

        }

        # 调用现有的流式对话接口
        from system.config import get_server_port

        api_url = f"http://localhost:{get_server_port('api_server')}/chat/stream"

        async with httpx.AsyncClient() as client:
            async with client.stream("POST", api_url, json=chat_request) as response:
                if response.status_code == 200:
                    # 处理流式响应，包括TTS切割
                    async for chunk in response.aiter_text():
                        if chunk.strip():
                            # 这里可以进一步处理流式响应
                            # 或者直接让UI处理流式响应
                            pass

                    logger.info(f"[UI发送] AI回复已成功发送到UI: {session_id}")
                    logger.info("[UI发送] 成功显示到UI")
                else:
                    logger.error(f"[UI发送] 调用流式对话接口失败: {response.status_code}")

    except Exception as e:
        logger.error(f"[UI发送] 触发聊天流式响应失败: {e}")


async def _send_ai_response_directly(session_id: str, response_text: str):
    """直接发送AI回复到UI"""
    try:
        import httpx

        # 使用非流式接口发送AI回复
        chat_request = {
            "message": f"[工具结果] {response_text}",  # 添加标记让UI知道这是工具结果
            "stream": False,
            "session_id": session_id,
            "disable_tts": False,
            "return_audio": False,

        }

        from system.config import get_server_port

        api_url = f"http://localhost:{get_server_port('api_server')}/chat"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(api_url, json=chat_request)
            if response.status_code == 200:
                logger.info(f"[直接发送] AI回复已通过非流式接口发送到UI: {session_id}")
            else:
                logger.error(f"[直接发送] 非流式接口发送失败: {response.status_code}")

    except Exception as e:
        logger.error(f"[直接发送] 直接发送AI回复失败: {e}")


# ============ 对话端点 ============


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """普通对话接口 - 仅处理纯文本对话"""

    if not request.message.strip():
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    try:
        # 更新ProactiveVision的用户活动时间
        asyncio.create_task(_update_proactive_activity_silent())

        # 技能调度前缀：让 LLM 明确知道当前处于技能模式
        user_message = request.message
        if request.skill:
            skill_labels = "，".join(f"【{s.strip()}】" for s in request.skill.split(",") if s.strip())
            user_message = f"调度技能{skill_labels}：{user_message}"
        session_id = message_manager.create_session(request.session_id, temporary=request.temporary)

        # 系统提示词 = 纯人格
        system_prompt = build_system_prompt()

        # 先构建对话消息（人格在 messages[0]）
        effective_message = user_message
        messages = message_manager.build_conversation_messages(
            session_id=session_id, system_prompt=system_prompt, current_message=effective_message
        )

        # RAG 记忆召回
        rag_section = ""

        async def _query_rag():
            nonlocal rag_section
            try:
                from summer_memory.memory_client import get_remote_memory_client

                remote_mem = get_remote_memory_client()
                if remote_mem:
                    mem_result = await remote_mem.query_memory(question=request.message, limit=5)
                    if mem_result.get("success") and mem_result.get("quintuples"):
                        quints = mem_result["quintuples"]
                        mem_lines = []
                        for q in quints:
                            if isinstance(q, (list, tuple)) and len(q) >= 5:
                                mem_lines.append(f"- {q[0]}({q[1]}) —[{q[2]}]→ {q[3]}({q[4]})")
                            elif isinstance(q, dict):
                                mem_lines.append(f"- {q.get('subject','')}({q.get('subject_type','')}) —[{q.get('predicate','')}]→ {q.get('object','')}({q.get('object_type','')})")
                        if mem_lines:
                            rag_section = "\n\n## 相关记忆\n\n以下是从知识图谱中检索到的与用户问题相关的记忆，请参考这些信息回答：\n" + "\n".join(mem_lines)
                            logger.info(f"[RAG] 召回 {len(mem_lines)} 条记忆注入上下文")
                    elif mem_result.get("success") and mem_result.get("answer"):
                        rag_section = f"\n\n## 相关记忆\n\n以下是从知识图谱中检索到的与用户问题相关的记忆：\n{mem_result['answer']}"
                        logger.info(f"[RAG] 召回记忆（answer 模式）注入上下文")
            except Exception as e:
                logger.debug(f"[RAG] 记忆召回失败（不影响对话）: {e}")

        await _query_rag()

        # 构建附加知识（工具走原生 function calling，不再文本注入）
        supplement = build_context_supplement(
            include_skills=True,
            include_tool_instructions=False,
            skill_name=request.skill,
            rag_section=rag_section,
        )
        messages.append({"role": "system", "content": supplement})

        # 使用整合后的LLM服务（支持 reasoning_content）
        llm_service = get_llm_service()
        llm_response = await llm_service.chat_with_context_and_reasoning(messages, get_config().api.temperature)

        # 处理完成
        # 统一保存对话历史与日志
        _save_conversation_and_logs(session_id, user_message, llm_response.content)

        return ChatResponse(
            response=extract_message(llm_response.content) if llm_response.content else llm_response.content,
            reasoning_content=llm_response.reasoning_content,
            session_id=session_id,
            status="success",
        )
    except Exception as e:
        print(f"对话处理错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """流式对话接口 - 使用 agentic tool loop 实现多轮工具调用"""

    if not request.message.strip():
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    # 技能调度前缀：让 LLM 明确知道当前处于技能模式
    user_message = request.message
    if request.skill:
        skill_labels = "，".join(f"【{s.strip()}】" for s in request.skill.split(",") if s.strip())
        user_message = f"调度技能{skill_labels}：{user_message}"

    async def generate_response() -> AsyncGenerator[str, None]:
        complete_text = ""  # 用于累积最终轮的完整文本（供 return_audio 模式使用）
        _mq_initialized = False  # 标记消息队列是否已设置 active
        try:
            import time as _time
            t_api_start = _time.monotonic()

            # 获取或创建会话ID
            session_id = message_manager.create_session(request.session_id, temporary=request.temporary)

            # ★ 通知对话开始 + 设置消息队列状态
            from apiserver.message_queue import get_message_queue
            mq = get_message_queue()
            mq.set_conversation_active(True)
            _mq_initialized = True
            asyncio.create_task(_notify_conversation_event("started"))

            # 发送会话ID信息
            yield f"data: session_id: {session_id}\n\n"

            # 系统提示词 = 纯人格
            system_prompt = build_system_prompt()

            # 用户消息使用带技能前缀的版本
            effective_message = user_message

            # ★ 检查是否有临时屏幕消息需要提升为正式上下文
            ephemeral = mq.promote_ephemeral_screen()
            if ephemeral:
                message_manager.add_message(session_id, "user", f"[屏幕观察] {ephemeral.content}")
                logger.info("[ChatStream] 提升临时屏幕消息为正式上下文")

            # 先构建对话消息（人格在 messages[0]）
            messages = message_manager.build_conversation_messages(
                session_id=session_id, system_prompt=system_prompt, current_message=effective_message
            )

            # ====== RAG 记忆召回 ======
            yield 'data: {"type":"status","text":"回忆中..."}\n\n'
            rag_section = ""

            async def _query_rag_stream():
                nonlocal rag_section
                try:
                    from summer_memory.memory_client import get_remote_memory_client

                    remote_mem = get_remote_memory_client()
                    if remote_mem:
                        mem_result = await remote_mem.query_memory(question=request.message, limit=5)
                        if mem_result.get("success") and mem_result.get("quintuples"):
                            quints = mem_result["quintuples"]
                            mem_lines = []
                            for q in quints:
                                if isinstance(q, (list, tuple)) and len(q) >= 5:
                                    mem_lines.append(f"- {q[0]}({q[1]}) —[{q[2]}]→ {q[3]}({q[4]})")
                                elif isinstance(q, dict):
                                    mem_lines.append(f"- {q.get('subject','')}({q.get('subject_type','')}) —[{q.get('predicate','')}]→ {q.get('object','')}({q.get('object_type','')})")
                            if mem_lines:
                                rag_section = "\n\n## 相关记忆\n\n以下是从知识图谱中检索到的与用户问题相关的记忆，请参考这些信息回答：\n" + "\n".join(mem_lines)
                                logger.info(f"[RAG] 召回 {len(mem_lines)} 条记忆注入上下文")
                        elif mem_result.get("success") and mem_result.get("answer"):
                            rag_section = f"\n\n## 相关记忆\n\n以下是从知识图谱中检索到的与用户问题相关的记忆：\n{mem_result['answer']}"
                            logger.info(f"[RAG] 召回记忆（answer 模式）注入上下文")
                except Exception as e:
                    logger.debug(f"[RAG] 记忆召回失败（不影响对话）: {e}")

            await _query_rag_stream()

            # 构建附加知识（工具走原生 function calling，不再文本注入）
            yield 'data: {"type":"status","text":"组织上下文"}\n\n'
            supplement = build_context_supplement(
                include_skills=True,
                include_tool_instructions=False,
                skill_name=request.skill,
                rag_section=rag_section,
            )
            messages.append({"role": "system", "content": supplement})

            # 获取工具 schemas（原生 function calling）
            from apiserver.tool_schemas import get_all_tool_schemas
            tools = get_all_tool_schemas()

            # 如果携带截屏图片，将最后一条 user 消息改为多模态格式（OpenAI vision 兼容）
            if request.images:
                # 找到最后一条 user 消息的索引（跳过末尾的 system supplement）
                user_idx = None
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i].get("role") == "user":
                        user_idx = i
                        break
                if user_idx is not None:
                    last_user_msg = messages[user_idx]
                    content_parts = [{"type": "text", "text": last_user_msg["content"]}]
                    for img_data in request.images:
                        content_parts.append({"type": "image_url", "image_url": {"url": img_data}})
                    messages[user_idx] = {
                        "role": "user",
                        "content": content_parts,
                    }

            # 初始化语音集成（根据voice_mode和return_audio决定）
            voice_integration = None

            should_enable_tts = (
                get_config().system.voice_enabled
                and not request.return_audio  # return_audio时不启用实时TTS
                and get_config().voice_realtime.voice_mode != "hybrid"
                and not request.disable_tts
                and not _is_voice_runtime_paused()
            )

            if should_enable_tts:
                try:
                    from voice.output.voice_integration import get_voice_integration

                    voice_integration = get_voice_integration()
                    logger.info(
                        f"[API Server] 实时语音集成已启用 (return_audio={request.return_audio}, voice_mode={get_config().voice_realtime.voice_mode})"
                    )
                except Exception as e:
                    print(f"语音集成初始化失败: {e}")
            else:
                if request.return_audio:
                    logger.info("[API Server] return_audio模式，将在最后生成完整音频")
                elif get_config().voice_realtime.voice_mode == "hybrid" and not request.return_audio:
                    logger.info("[API Server] 混合模式下且未请求音频，不处理TTS")
                elif request.disable_tts:
                    logger.info("[API Server] 客户端禁用了TTS (disable_tts=True)")

            # 初始化流式文本切割器（仅用于TTS处理）
            tool_extractor = None
            try:
                from apiserver.streaming_tool_extractor import StreamingToolCallExtractor

                tool_extractor = StreamingToolCallExtractor()
                if voice_integration and not request.return_audio:
                    tool_extractor.set_callbacks(
                        on_text_chunk=None,
                        voice_integration=voice_integration,
                    )
            except Exception as e:
                print(f"流式文本切割器初始化失败: {e}")

            # ====== Agentic Tool Loop ======
            yield 'data: {"type":"status","text":"娜迦打字中..."}\n\n'
            from apiserver.agentic_tool_loop import run_agentic_loop

            t_prepare_elapsed = _time.monotonic() - t_api_start
            logger.info(f"[ChatStream] 预处理完成: {t_prepare_elapsed:.2f}s "
                        f"(消息构建+RAG+启动压缩+supplement+voice初始化)")

            # 如果本次携带图片，标记此会话为 VLM 会话
            if request.images:
                _vlm_sessions.add(session_id)

            # 如果当前会话曾发送过图片，持续使用视觉模型
            model_override = None
            use_vlm = session_id in _vlm_sessions
            cc = get_config().computer_control
            if use_vlm and cc.enabled and (cc.api_key or naga_auth.is_authenticated()):
                model_override = {
                    "model": cc.model,
                    "api_base": cc.model_url,
                    "api_key": cc.api_key,
                }
                logger.info(f"[API Server] VLM 会话，使用视觉模型: {cc.model}")

            complete_reasoning = ""
            # 记录每轮的content，用于在每轮结束时完成TTS处理
            current_round_text = ""
            is_tool_event = False  # 标记当前是否在处理工具事件（不送TTS）
            was_compressed = False  # 运行时是否执行过上下文压缩（用于保存 info 标记）

            async for chunk in run_agentic_loop(messages, session_id, model_override=model_override, tools=tools):
                if chunk.startswith("data: "):
                    try:
                        import json as json_module

                        data_str = chunk[6:].strip()
                        if data_str and data_str != "[DONE]":
                            chunk_data = json_module.loads(data_str)
                            chunk_type = chunk_data.get("type", "content")
                            chunk_text = chunk_data.get("text", "")

                            if chunk_type == "content":
                                # 累积本轮内容（TTS + 保存）
                                current_round_text += chunk_text
                                if request.return_audio:
                                    complete_text += chunk_text
                                # TTS：每轮的正常content都发送（不含工具内容）
                                if tool_extractor and not is_tool_event:
                                    asyncio.create_task(tool_extractor.process_text_chunk(chunk_text))
                            elif chunk_type == "reasoning":
                                complete_reasoning += chunk_text
                            elif chunk_type == "round_end":
                                # 每轮结束时，完成TTS处理并重置
                                has_more = chunk_data.get("has_more", False)
                                if has_more and tool_extractor and not request.return_audio:
                                    # 中间轮结束，flush TTS缓冲
                                    try:
                                        await tool_extractor.finish_processing()
                                    except Exception as e:
                                        logger.debug(f"中间轮TTS flush失败: {e}")
                                    if voice_integration:
                                        try:
                                            threading.Thread(
                                                target=voice_integration.finish_processing,
                                                daemon=True,
                                            ).start()
                                        except Exception:
                                            pass
                                    # 重新初始化 tool_extractor 给下一轮使用
                                    try:
                                        from apiserver.streaming_tool_extractor import StreamingToolCallExtractor
                                        tool_extractor = StreamingToolCallExtractor()
                                        if voice_integration and not request.return_audio:
                                            tool_extractor.set_callbacks(
                                                on_text_chunk=None,
                                                voice_integration=voice_integration,
                                            )
                                    except Exception:
                                        pass
                                current_round_text = ""
                            elif chunk_type == "tool_calls":
                                is_tool_event = True
                            elif chunk_type == "tool_results":
                                is_tool_event = True
                            elif chunk_type == "round_start":
                                # 新一轮开始，重置工具事件标记
                                is_tool_event = False
                            elif chunk_type == "compress_info":
                                # 运行时压缩完成，标记后续需要保存 info 消息
                                was_compressed = True

                            # 透传所有 chunk 给前端（content/reasoning/tool events）
                            yield chunk
                            continue
                    except Exception as e:
                        logger.error(f"[API Server] 流式数据解析错误: {e}")

                yield chunk

            # ====== 流式处理完成 ======

            # V19: 如果请求返回音频，在这里生成并返回音频URL
            if request.return_audio and complete_text:
                try:
                    logger.info(f"[API Server V19] 生成音频，文本长度: {len(complete_text)}")

                    from voice.tts_wrapper import generate_speech_safe

                    tts_voice = get_config().voice_realtime.tts_voice or "zh-CN-XiaoyiNeural"
                    audio_file = generate_speech_safe(
                        text=complete_text, voice=tts_voice, response_format="mp3", speed=1.0
                    )

                    try:
                        from voice.output.voice_integration import get_voice_integration

                        voice_integration = get_voice_integration()
                        voice_integration.receive_audio_url(audio_file)
                        logger.info(f"[API Server V19] 音频已直接播放: {audio_file}")
                    except Exception as e:
                        logger.error(f"[API Server V19] 音频播放失败: {e}")
                        yield f"data: audio_url: {audio_file}\n\n"

                except Exception as e:
                    logger.error(f"[API Server V19] 音频生成失败: {e}")
                    traceback.print_exc()

            # 完成流式文本切割器处理（最终轮）
            if tool_extractor and not request.return_audio:
                try:
                    await tool_extractor.finish_processing()
                except Exception as e:
                    print(f"流式文本切割器完成处理错误: {e}")

            # 完成语音处理（最终轮）
            if voice_integration and not request.return_audio:
                try:
                    threading.Thread(
                        target=voice_integration.finish_processing,
                        daemon=True,
                    ).start()
                except Exception as e:
                    print(f"语音集成完成处理错误: {e}")

            # 获取完整文本用于保存
            complete_response = ""
            if tool_extractor:
                try:
                    complete_response = tool_extractor.get_complete_text()
                except Exception as e:
                    print(f"获取完整响应文本失败: {e}")
            elif request.return_audio:
                complete_response = complete_text

            # fallback: 如果 tool_extractor 没有累积到文本，使用最后一轮的 current_round_text
            if not complete_response and current_round_text:
                complete_response = current_round_text

            # 统一保存对话历史与日志
            _save_conversation_and_logs(session_id, user_message, complete_response)

            # ★ 通知对话结束 + 设置消息队列状态
            mq.set_conversation_active(False)
            asyncio.create_task(_notify_conversation_event("ended"))

            # 运行时压缩成功时，在会话末尾追加 info 标记
            # 该标记持久化到磁盘，下次启动用于判断上一个会话是否已被压缩
            if was_compressed:
                message_manager.add_message(session_id, "info", "【已压缩上下文】")

            # [DONE] 信号已由 llm_service.stream_chat_with_context 发送，无需重复

        except Exception as e:
            print(f"流式对话处理错误: {e}")
            traceback.print_exc()
            yield f"data: error:{str(e)}\n\n"
        finally:
            # ★ 确保对话结束事件一定触发，即使异常/客户端断开
            if _mq_initialized:
                try:
                    from apiserver.message_queue import get_message_queue
                    _mq = get_message_queue()
                    if _mq.is_conversation_active():
                        _mq.set_conversation_active(False)
                        asyncio.create_task(_notify_conversation_event("ended"))
                except Exception:
                    pass

    return StreamingResponse(
        generate_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "X-Accel-Buffering": "no",  # 禁用nginx缓冲
        },
    )
