#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NagaAgent独立服务 - 通过OpenClaw执行任务
提供意图识别和OpenClaw任务调度功能
"""

import asyncio
import uuid
import shutil
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager

from system.config import config, add_config_listener, logger
from agentserver.task_scheduler import get_task_scheduler, TaskStep
from agentserver.openclaw import get_openclaw_client, set_openclaw_config
from agentserver.openclaw.embedded_runtime import get_embedded_runtime, EmbeddedRuntime

# 配置日志
logger = logging.getLogger(__name__)


async def _start_gateway_if_port_free(runtime: EmbeddedRuntime) -> bool:
    """有相关进程或端口占用则跳过，否则启动 Gateway。"""
    if runtime.gateway_running:
        logger.info("当前进程中的 OpenClaw Gateway 已在运行，跳过启动")
        return False

    if runtime.has_gateway_process():
        logger.info("检测到已有 OpenClaw Gateway 相关进程，跳过启动")
        return False

    if runtime.is_gateway_port_in_use():
        logger.info("端口 18789 已被占用，跳过 Gateway 启动")
        return False

    gw_ok = await runtime.start_gateway()
    if gw_ok:
        logger.info("OpenClaw Gateway 启动成功")
    else:
        logger.warning("OpenClaw Gateway 启动失败")
    return gw_ok


async def _auto_install_openclaw() -> bool:
    """尝试通过 npm install -g openclaw 自动安装"""
    npm = shutil.which("npm")
    if not npm:
        logger.warning("自动安装 OpenClaw 失败：npm 不可用")
        return False

    try:
        logger.info("OpenClaw 未安装，正在执行 npm install -g openclaw，请稍候...")
        proc = await asyncio.create_subprocess_exec(
            npm,
            "install",
            "-g",
            "openclaw",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode != 0:
            logger.error(f"npm install -g openclaw 失败: {stderr.decode()[:500]}")
            return False

        # 验证安装成功
        if shutil.which("openclaw"):
            logger.info("OpenClaw 自动安装成功")
            return True
        else:
            logger.error("npm install -g openclaw 执行成功但 openclaw 命令未找到")
            return False

    except asyncio.TimeoutError:
        logger.error("npm install -g openclaw 超时（120秒）")
        return False
    except Exception as e:
        logger.error(f"自动安装 OpenClaw 失败: {e}")
        return False


def _should_use_embedded_openclaw(runtime: EmbeddedRuntime) -> bool:
    """是否应优先使用内嵌 OpenClaw（仅打包环境且用户本机未安装）"""
    return runtime.is_packaged and runtime.openclaw_installed and not runtime.has_global_install


def _on_config_changed() -> None:
    """配置变更监听器：自动更新 OpenClaw LLM 配置"""
    try:
        embedded_runtime = get_embedded_runtime()

        # 仅在使用内嵌 OpenClaw 时更新配置
        if _should_use_embedded_openclaw(embedded_runtime):
            from agentserver.openclaw.llm_config_bridge import inject_naga_llm_config

            inject_naga_llm_config()
            logger.info("配置变更：已更新内嵌 OpenClaw LLM 配置")
    except Exception as e:
        logger.warning(f"配置变更时更新 OpenClaw 配置失败: {e}")


def _is_port_in_use(port: int) -> bool:
    """检测端口是否被占用"""
    import socket

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        return result == 0
    except Exception:
        return False


async def _delayed_health_check():
    """延迟健康检查（等待所有服务启动）"""
    await asyncio.sleep(6)  # 虚拟机/低性能环境下启动更慢，适当延长缓冲时间

    try:
        from system.health_check import perform_startup_health_check
        await perform_startup_health_check()
    except Exception as e:
        logger.error(f"启动时健康检查失败: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI应用生命周期"""
    # startup
    try:
        # 初始化任务调度器
        Modules.task_scheduler = get_task_scheduler()

        # 设置LLM配置用于智能压缩
        if hasattr(config, "api") and config.api:
            llm_config = {"model": config.api.model, "api_key": config.api.api_key, "api_base": config.api.base_url}
            Modules.task_scheduler.set_llm_config(llm_config)

        # 初始化 OpenClaw 客户端 - 三层回退策略
        try:
            from agentserver.openclaw import detect_openclaw, OpenClawConfig as ClientOpenClawConfig
            from agentserver.openclaw.llm_config_bridge import (
                ensure_openclaw_config,
                inject_naga_llm_config,
                ensure_hooks_allow_request_session_key,
                ensure_gateway_local_mode,
                ensure_hooks_path,
            )

            embedded_runtime = get_embedded_runtime()
            mode = embedded_runtime.runtime_mode
            logger.info(f"OpenClaw 运行时模式: {mode}")
            has_global_openclaw: bool = False
            has_embedded_openclaw: bool = False

            if embedded_runtime.is_packaged:
                has_global_openclaw = shutil.which("openclaw") is not None
                has_embedded_openclaw = embedded_runtime.openclaw_installed

                if has_global_openclaw:
                    logger.info("打包环境：检测到全局安装 OpenClaw，跳过内嵌 OpenClaw 初始化/启动")
                else:
                    logger.info("打包环境：准备启动内嵌 OpenClaw Gateway")

                    # 首次运行时自动执行 onboard 初始化（含 fallback 配置生成）
                    onboard_ok = await embedded_runtime.ensure_onboarded()
                    if not onboard_ok:
                        logger.error("OpenClaw 初始化失败（onboard + fallback 均失败）")

                    # 检测端口是否已被占用
                    if _is_port_in_use(18789):
                        logger.info("端口 18789 已被占用，跳过内嵌 Gateway 启动")
                    else:
                        gw_ok = await embedded_runtime.start_gateway()
                        if gw_ok:
                            logger.info("内嵌 OpenClaw Gateway 启动成功")
                        else:
                            logger.error("内嵌 OpenClaw Gateway 启动失败")

            # === 打包环境 ===
            if embedded_runtime.is_packaged:
                if has_global_openclaw:
                    logger.info("打包环境：检测到全局安装的 OpenClaw，优先使用")
                    # 记录使用系统已有，避免卸载时误清理用户目录
                    state_file = embedded_runtime._get_install_state_file()
                    if state_file and (not state_file.exists() or embedded_runtime.is_auto_installed):
                        embedded_runtime._write_install_state(auto_installed=False)
                elif has_embedded_openclaw:
                    logger.info("打包环境：未检测到全局 OpenClaw，使用预装内嵌 OpenClaw")
                    # 记录为自动安装，保证卸载时可清理内嵌运行时相关目录
                    if not embedded_runtime.is_auto_installed:
                        embedded_runtime._write_install_state(auto_installed=True)
                else:
                    logger.warning("打包环境：未检测到全局 OpenClaw，且内嵌 OpenClaw 不可用")

            # === 开发环境 ===
            else:
                if mode == "global":
                    logger.info("检测到全局安装的 OpenClaw")
                else:
                    # 尝试自动安装 openclaw
                    installed = await _auto_install_openclaw()
                    if not installed:
                        logger.warning("OpenClaw 不可用：未全局安装，自动安装也失败")
                has_global_openclaw = shutil.which("openclaw") is not None

            # === 统一：按运行时来源处理配置与 Gateway ===
            openclaw_available = has_global_openclaw or has_embedded_openclaw
            if openclaw_available:
                use_embedded_openclaw = _should_use_embedded_openclaw(embedded_runtime)
                # 兼容旧配置：内嵌 Gateway 场景下补齐 gateway.mode=local，避免启动被阻塞
                if use_embedded_openclaw:
                    ensure_gateway_local_mode(auto_create=False)
                    # 兼容 OpenClaw 2026.2.17+：确保 hooks 允许外部 sessionKey
                    ensure_hooks_allow_request_session_key(auto_create=False)
                # 确保 hooks.path 显式设置，避免 Gateway 不注册 hooks 路由（405）
                ensure_hooks_path(auto_create=False)

                # 确保配置文件存在（全局/内嵌均需要）
                ensure_openclaw_config()
                # 仅在内嵌 OpenClaw 场景下注入 Naga LLM 配置
                if use_embedded_openclaw:
                    inject_naga_llm_config()
                    logger.info("已自动注入内嵌 OpenClaw 的 Naga LLM 配置")

                if embedded_runtime.is_packaged:
                    if use_embedded_openclaw:
                        await _start_gateway_if_port_free(embedded_runtime)
                    elif has_global_openclaw:
                        logger.info("打包环境：使用全局 OpenClaw，跳过内嵌 Gateway 启动")
                else:
                    await _start_gateway_if_port_free(embedded_runtime)

            # 检测最终状态并初始化客户端
            openclaw_status = detect_openclaw(check_connection=False)

            if openclaw_status.installed:
                openclaw_config = ClientOpenClawConfig(
                    gateway_url=openclaw_status.gateway_url or "http://127.0.0.1:18789",
                    gateway_token=openclaw_status.gateway_token,
                    hooks_token=openclaw_status.hooks_token,
                    hooks_path=getattr(openclaw_status, "hooks_path", "/hooks"),
                    timeout=120,
                )
                logger.info(f"OpenClaw 配置: {openclaw_config.gateway_url}")
                logger.info(
                    f"  - gateway_token: {'***' + openclaw_config.gateway_token[-8:] if openclaw_config.gateway_token else '未配置'}"
                )
                logger.info(
                    f"  - hooks_token: {'***' + openclaw_config.hooks_token[-8:] if openclaw_config.hooks_token else '未配置'}"
                )
            else:
                openclaw_config = ClientOpenClawConfig(
                    gateway_url=getattr(config.openclaw, "gateway_url", "http://127.0.0.1:18789")
                    if hasattr(config, "openclaw")
                    else "http://127.0.0.1:18789",
                    gateway_token=getattr(config.openclaw, "gateway_token", None)
                    if hasattr(config, "openclaw")
                    else None,
                    hooks_token=getattr(config.openclaw, "hooks_token", None) if hasattr(config, "openclaw") else None,
                    hooks_path=getattr(config.openclaw, "hooks_path", "/hooks")
                    if hasattr(config, "openclaw")
                    else "/hooks",
                    timeout=120,
                )
                logger.info(f"OpenClaw 未检测到安装，使用配置文件: {openclaw_config.gateway_url}")

            Modules.openclaw_client = get_openclaw_client(openclaw_config)
            Modules.openclaw_client.restore_session()
            logger.info(f"OpenClaw客户端初始化完成: {openclaw_config.gateway_url}")
        except Exception as e:
            logger.warning(f"OpenClaw客户端初始化失败（可选功能）: {e}")
            Modules.openclaw_client = None

        # 注册配置变更监听器
        add_config_listener(_on_config_changed)
        logger.debug("已注册 OpenClaw 配置变更监听器")

        # 初始化主动视觉系统
        try:
            from agentserver.proactive_vision import (
                load_proactive_config,
                create_proactive_scheduler,
                create_proactive_analyzer,
                create_proactive_trigger,
            )

            pv_config = load_proactive_config()
            create_proactive_trigger()
            create_proactive_analyzer(pv_config)
            Modules.proactive_scheduler = create_proactive_scheduler(pv_config)

            if pv_config.enabled:
                await Modules.proactive_scheduler.start()
                logger.info("[ProactiveVision] 主动视觉系统已启动")
            else:
                logger.info("[ProactiveVision] 主动视觉系统未启用")
        except Exception as e:
            logger.warning(f"[ProactiveVision] 初始化失败（可选功能）: {e}")
            Modules.proactive_scheduler = None

        logger.info("NagaAgent服务初始化完成")

        # 执行启动时健康检查（延迟2秒等待所有服务就绪）
        asyncio.create_task(_delayed_health_check())

    except Exception as e:
        logger.error(f"服务初始化失败: {e}")
        raise

    # 运行期
    yield

    # shutdown
    try:
        # 停止主动视觉系统
        if Modules.proactive_scheduler:
            await Modules.proactive_scheduler.stop()
            logger.info("[ProactiveVision] 主动视觉系统已停止")

        # 停止 Gateway 进程（内嵌模式）
        embedded_runtime = get_embedded_runtime()
        if embedded_runtime.gateway_running:
            await embedded_runtime.stop_gateway()

        logger.info("NagaAgent服务已关闭")
    except Exception as e:
        logger.error(f"服务关闭失败: {e}")


app = FastAPI(title="NagaAgent Server", version="1.0.0", lifespan=lifespan)


class Modules:
    """全局模块管理器"""

    task_scheduler = None
    openclaw_client = None
    proactive_scheduler = None  # 主动视觉调度器


def _now_iso() -> str:
    """获取当前时间ISO格式"""
    return datetime.now().isoformat()


async def _process_openclaw_task(instruction: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    """通过 OpenClaw 执行任务"""
    try:
        if not Modules.openclaw_client:
            return {
                "success": False,
                "error": "OpenClaw 客户端未初始化",
                "task_type": "openclaw",
                "instruction": instruction,
            }

        logger.info(f"开始通过 OpenClaw 执行任务: {instruction}")

        task = await Modules.openclaw_client.send_message(
            message=instruction,
            session_key=session_id,
            name="NagaAgent",
        )

        logger.info(f"OpenClaw 任务完成: {instruction}, 状态: {task.status.value}")
        return {
            "success": task.status.value == "completed",
            "result": task.to_dict(),
            "task_type": "openclaw",
            "instruction": instruction,
        }

    except Exception as e:
        logger.error(f"OpenClaw 任务失败: {e}")
        return {"success": False, "error": str(e), "task_type": "openclaw", "instruction": instruction}


async def _execute_agent_tasks_async(
    agent_calls: List[Dict[str, Any]],
    session_id: str,
    analysis_session_id: str,
    request_id: str,
    callback_url: Optional[str] = None,
):
    """异步执行Agent任务 - 应用与MCP服务器相同的会话管理逻辑"""
    try:
        logger.info(f"[异步执行] 开始执行 {len(agent_calls)} 个Agent任务")

        # 处理每个Agent任务
        results = []
        for i, agent_call in enumerate(agent_calls):
            try:
                instruction = agent_call.get("instruction", "")
                tool_name = agent_call.get("tool_name", "未知工具")
                service_name = agent_call.get("service_name", "未知服务")

                logger.info(f"[异步执行] 执行任务 {i + 1}/{len(agent_calls)}: {tool_name} - {instruction}")

                # 添加任务步骤到调度器
                await Modules.task_scheduler.add_task_step(
                    request_id,
                    TaskStep(
                        step_id=f"step_{i + 1}",
                        task_id=request_id,
                        purpose=f"执行Agent任务: {tool_name}",
                        content=instruction,
                        output="",
                        analysis=None,
                        success=True,
                    ),
                )

                # 通过 OpenClaw 执行任务
                result = await _process_openclaw_task(instruction, session_id)
                results.append({"agent_call": agent_call, "result": result, "step_index": i})

                # 更新任务步骤结果
                await Modules.task_scheduler.add_task_step(
                    request_id,
                    TaskStep(
                        step_id=f"step_{i + 1}_result",
                        task_id=request_id,
                        purpose=f"任务结果: {tool_name}",
                        content=f"执行结果: {result.get('success', False)}",
                        output=str(result.get("result", "")),
                        analysis={
                            "analysis": f"任务类型: {result.get('task_type', 'unknown')}, 工具: {tool_name}, 服务: {service_name}"
                        },
                        success=result.get("success", False),
                        error=result.get("error"),
                    ),
                )

                logger.info(f"[异步执行] 任务 {i + 1} 完成: {result.get('success', False)}")

            except Exception as e:
                logger.error(f"[异步执行] 任务 {i + 1} 执行失败: {e}")
                results.append(
                    {"agent_call": agent_call, "result": {"success": False, "error": str(e)}, "step_index": i}
                )

        # 发送回调通知（如果提供了回调URL）
        if callback_url:
            await _send_callback_notification(callback_url, request_id, session_id, analysis_session_id, results)

        logger.info(f"[异步执行] 所有Agent任务执行完成: {len(results)} 个任务")

    except Exception as e:
        logger.error(f"[异步执行] Agent任务执行失败: {e}")
        # 发送错误回调
        if callback_url:
            await _send_callback_notification(callback_url, request_id, session_id, analysis_session_id, [], str(e))


async def _send_callback_notification(
    callback_url: str,
    request_id: str,
    session_id: str,
    analysis_session_id: str,
    results: List[Dict[str, Any]],
    error: Optional[str] = None,
):
    """发送回调通知 - 应用与MCP服务器相同的回调机制"""
    try:
        import httpx

        callback_payload = {
            "request_id": request_id,
            "session_id": session_id,
            "analysis_session_id": analysis_session_id,
            "success": error is None,
            "error": error,
            "results": results,
            "completed_at": _now_iso(),
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(callback_url, json=callback_payload)
            if response.status_code == 200:
                logger.info(f"[回调通知] Agent任务结果回调成功: {request_id}")
            else:
                logger.error(f"[回调通知] Agent任务结果回调失败: {response.status_code}")

    except Exception as e:
        logger.error(f"[回调通知] 发送Agent任务回调失败: {e}")


# ============ API端点 ============


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "timestamp": _now_iso(),
        "modules": {
            "openclaw": Modules.openclaw_client is not None,
            "proactive_vision": Modules.proactive_scheduler is not None,
        },
    }


@app.get("/health/full")
async def full_health_check():
    """完整健康检查（包括所有服务）"""
    from system.health_check import get_health_checker

    checker = get_health_checker()
    results = await checker.check_all()
    summary = checker.get_summary(results)

    # 转换为可序列化格式
    results_dict = {}
    for service_name, result in results.items():
        results_dict[service_name] = {
            "status": result.status.value,
            "message": result.message,
            "checks": result.checks,
            "details": result.details,
            "latency_ms": result.latency_ms,
        }

    return {
        "summary": summary,
        "services": results_dict,
        "timestamp": _now_iso(),
    }


@app.post("/schedule")
async def schedule_agent_tasks(payload: Dict[str, Any]):
    """统一的任务调度端点 - 应用与MCP服务器相同的会话管理逻辑"""
    if not Modules.openclaw_client or not Modules.task_scheduler:
        raise HTTPException(503, "OpenClaw客户端或任务调度器未就绪")

    # 提取新的请求格式参数
    query = payload.get("query", "")
    agent_calls = payload.get("agent_calls", [])
    session_id = payload.get("session_id")
    analysis_session_id = payload.get("analysis_session_id")
    request_id = payload.get("request_id", str(uuid.uuid4()))
    callback_url = payload.get("callback_url")

    try:
        logger.info(f"[统一调度] 接收Agent任务调度请求: {query}")
        logger.info(f"[统一调度] 会话ID: {session_id}, 分析会话ID: {analysis_session_id}, 请求ID: {request_id}")

        if not agent_calls:
            return {
                "success": True,
                "status": "no_tasks",
                "message": "未发现可执行的Agent任务",
                "task_id": request_id,
                "accepted_at": _now_iso(),
                "session_id": session_id,
                "analysis_session_id": analysis_session_id,
            }

        logger.info(f"[统一调度] 会话 {session_id} 发现 {len(agent_calls)} 个Agent任务")

        # 创建任务调度器任务
        task_id = await Modules.task_scheduler.create_task(
            task_id=request_id,
            purpose=f"执行Agent任务: {query}",
            session_id=session_id,
            analysis_session_id=analysis_session_id,
        )

        # 异步执行任务（不阻塞响应）
        asyncio.create_task(
            _execute_agent_tasks_async(agent_calls, session_id, analysis_session_id, request_id, callback_url)
        )

        return {
            "success": True,
            "status": "scheduled",
            "task_id": request_id,
            "message": f"已调度 {len(agent_calls)} 个Agent任务",
            "accepted_at": _now_iso(),
            "session_id": session_id,
            "analysis_session_id": analysis_session_id,
        }

    except Exception as e:
        logger.error(f"[统一调度] Agent任务调度失败: {e}")
        raise HTTPException(500, f"调度失败: {e}")


@app.post("/analyze_and_execute")
async def analyze_and_execute(payload: Dict[str, Any]):
    """意图分析和任务执行 - 保持向后兼容"""
    if not Modules.openclaw_client:
        raise HTTPException(503, "OpenClaw客户端未就绪")

    messages = (payload or {}).get("messages", [])
    if not isinstance(messages, list):
        raise HTTPException(400, "messages必须是{role, content}格式的列表")

    session_id = (payload or {}).get("session_id")

    try:
        # 直接执行电脑控制任务，不进行意图分析
        # 意图分析已在API服务器中完成，这里只负责执行具体的Agent任务

        # 从消息中提取任务指令
        tasks = []
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if "执行Agent任务:" in content:
                    # 提取任务指令
                    instruction = content.replace("执行Agent任务:", "").strip()
                    tasks.append({"instruction": instruction})

        if not tasks:
            return {
                "success": True,
                "status": "no_tasks",
                "message": "未发现可执行的任务",
                "accepted_at": _now_iso(),
                "session_id": session_id,
            }

        logger.info(f"会话 {session_id} 发现 {len(tasks)} 个任务")

        # 通过 OpenClaw 处理每个任务
        results = []
        for task_instruction in tasks:
            result = await _process_openclaw_task(task_instruction["instruction"], session_id)
            results.append(result)

        return {
            "success": True,
            "status": "completed",
            "tasks_processed": len(tasks),
            "results": results,
            "accepted_at": _now_iso(),
            "session_id": session_id,
        }

    except Exception as e:
        logger.error(f"意图分析和任务执行失败: {e}")
        raise HTTPException(500, f"处理失败: {e}")


# ============ 任务记忆管理API ============


@app.get("/tasks")
async def get_tasks(session_id: Optional[str] = None):
    """获取任务列表"""
    if not Modules.task_scheduler:
        raise HTTPException(503, "任务调度器未就绪")

    try:
        running_tasks = await Modules.task_scheduler.get_running_tasks()
        return {"success": True, "running_tasks": running_tasks, "session_id": session_id}
    except Exception as e:
        logger.error(f"获取任务列表失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """获取指定任务状态"""
    if not Modules.task_scheduler:
        raise HTTPException(503, "任务调度器未就绪")

    try:
        task_status = await Modules.task_scheduler.get_task_status(task_id)
        if not task_status:
            raise HTTPException(404, f"任务 {task_id} 不存在")

        return {"success": True, "task": task_status}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取任务状态失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.get("/tasks/{task_id}/memory")
async def get_task_memory(task_id: str, include_key_facts: bool = True):
    """获取任务记忆摘要"""
    if not Modules.task_scheduler:
        raise HTTPException(503, "任务调度器未就绪")

    try:
        memory_summary = await Modules.task_scheduler.get_task_memory_summary(task_id, include_key_facts)
        return {"success": True, "task_id": task_id, "memory_summary": memory_summary}
    except Exception as e:
        logger.error(f"获取任务记忆失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.get("/memory/global")
async def get_global_memory():
    """获取全局记忆摘要"""
    if not Modules.task_scheduler:
        raise HTTPException(503, "任务调度器未就绪")

    try:
        global_summary = await Modules.task_scheduler.get_global_memory_summary()
        failed_attempts = await Modules.task_scheduler.get_failed_attempts_summary()

        return {"success": True, "global_summary": global_summary, "failed_attempts": failed_attempts}
    except Exception as e:
        logger.error(f"获取全局记忆失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.post("/tasks/{task_id}/steps")
async def add_task_step(task_id: str, payload: Dict[str, Any]):
    """添加任务步骤"""
    if not Modules.task_scheduler:
        raise HTTPException(503, "任务调度器未就绪")

    try:
        step = TaskStep(
            step_id=payload.get("step_id", str(uuid.uuid4())),
            task_id=task_id,
            purpose=payload.get("purpose", "执行步骤"),
            content=payload.get("content", ""),
            output=payload.get("output", ""),
            analysis=payload.get("analysis"),
            success=payload.get("success", True),
            error=payload.get("error"),
        )

        await Modules.task_scheduler.add_task_step(task_id, step)

        return {"success": True, "message": "步骤添加成功", "step_id": step.step_id}
    except Exception as e:
        logger.error(f"添加任务步骤失败: {e}")
        raise HTTPException(500, f"添加失败: {e}")


@app.delete("/tasks/{task_id}/memory")
async def clear_task_memory(task_id: str):
    """清除任务记忆"""
    if not Modules.task_scheduler:
        raise HTTPException(503, "任务调度器未就绪")

    try:
        success = await Modules.task_scheduler.clear_task_memory(task_id)
        if not success:
            raise HTTPException(404, f"任务 {task_id} 不存在")

        return {"success": True, "message": f"任务 {task_id} 的记忆已清除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"清除任务记忆失败: {e}")
        raise HTTPException(500, f"清除失败: {e}")


@app.delete("/memory/global")
async def clear_global_memory():
    """清除全局记忆"""
    if not Modules.task_scheduler:
        raise HTTPException(503, "任务调度器未就绪")

    try:
        await Modules.task_scheduler.clear_all_memory()
        return {"success": True, "message": "全局记忆已清除"}
    except Exception as e:
        logger.error(f"清除全局记忆失败: {e}")
        raise HTTPException(500, f"清除失败: {e}")


# ============ 会话级别的记忆管理API ============


@app.get("/sessions")
async def get_all_sessions():
    """获取所有会话的摘要信息"""
    if not Modules.task_scheduler:
        raise HTTPException(503, "任务调度器未就绪")

    try:
        sessions = await Modules.task_scheduler.get_all_sessions()
        return {"success": True, "sessions": sessions, "total_sessions": len(sessions)}
    except Exception as e:
        logger.error(f"获取会话列表失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.get("/sessions/{session_id}/memory")
async def get_session_memory_summary(session_id: str):
    """获取会话记忆摘要"""
    if not Modules.task_scheduler:
        raise HTTPException(503, "任务调度器未就绪")

    try:
        summary = await Modules.task_scheduler.get_session_memory_summary(session_id)
        if "error" in summary:
            raise HTTPException(404, summary["error"])

        return {"success": True, "session_id": session_id, "memory_summary": summary}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话记忆摘要失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.get("/sessions/{session_id}/compressed_memories")
async def get_session_compressed_memories(session_id: str):
    """获取会话的压缩记忆"""
    if not Modules.task_scheduler:
        raise HTTPException(503, "任务调度器未就绪")

    try:
        memories = await Modules.task_scheduler.get_session_compressed_memories(session_id)
        return {"success": True, "session_id": session_id, "compressed_memories": memories, "count": len(memories)}
    except Exception as e:
        logger.error(f"获取会话压缩记忆失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.get("/sessions/{session_id}/key_facts")
async def get_session_key_facts(session_id: str):
    """获取会话的关键事实"""
    if not Modules.task_scheduler:
        raise HTTPException(503, "任务调度器未就绪")

    try:
        key_facts = await Modules.task_scheduler.get_session_key_facts(session_id)
        return {"success": True, "session_id": session_id, "key_facts": key_facts, "count": len(key_facts)}
    except Exception as e:
        logger.error(f"获取会话关键事实失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.get("/sessions/{session_id}/failed_attempts")
async def get_session_failed_attempts(session_id: str):
    """获取会话的失败尝试"""
    if not Modules.task_scheduler:
        raise HTTPException(503, "任务调度器未就绪")

    try:
        failed_attempts = await Modules.task_scheduler.get_session_failed_attempts(session_id)
        return {
            "success": True,
            "session_id": session_id,
            "failed_attempts": failed_attempts,
            "count": len(failed_attempts),
        }
    except Exception as e:
        logger.error(f"获取会话失败尝试失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.get("/sessions/{session_id}/tasks")
async def get_session_tasks(session_id: str):
    """获取会话的所有任务"""
    if not Modules.task_scheduler:
        raise HTTPException(503, "任务调度器未就绪")

    try:
        tasks = await Modules.task_scheduler.get_session_tasks(session_id)
        return {"success": True, "session_id": session_id, "tasks": tasks, "count": len(tasks)}
    except Exception as e:
        logger.error(f"获取会话任务失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.delete("/sessions/{session_id}/memory")
async def clear_session_memory(session_id: str):
    """清除指定会话的记忆"""
    if not Modules.task_scheduler:
        raise HTTPException(503, "任务调度器未就绪")

    try:
        success = await Modules.task_scheduler.clear_session_memory(session_id)
        if not success:
            raise HTTPException(404, f"会话 {session_id} 不存在")

        return {"success": True, "message": f"会话 {session_id} 的记忆已清除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"清除会话记忆失败: {e}")
        raise HTTPException(500, f"清除失败: {e}")


# ============ OpenClaw 集成 API ============


@app.get("/openclaw/health")
async def openclaw_health_check():
    """检查 OpenClaw Gateway 健康状态"""
    if not Modules.openclaw_client:
        return {"success": False, "status": "not_configured", "message": "OpenClaw 客户端未配置"}

    try:
        health = await Modules.openclaw_client.health_check()
        return {"success": True, "health": health}
    except Exception as e:
        logger.error(f"OpenClaw 健康检查失败: {e}")
        return {"success": False, "status": "error", "error": str(e)}


@app.post("/openclaw/config")
async def configure_openclaw(payload: Dict[str, Any]):
    """配置 OpenClaw 连接

    请求体:
    - gateway_url: Gateway 地址 (默认 http://localhost:18789)
    - token: 认证 token
    - timeout: 超时时间
    - default_model: 默认模型
    - default_channel: 默认通道
    """
    try:
        from agentserver.openclaw import OpenClawConfig as ClientOpenClawConfig

        openclaw_config = ClientOpenClawConfig(
            gateway_url=payload.get("gateway_url", "http://localhost:18789"),
            token=payload.get("token"),
            hooks_path=payload.get("hooks_path", "/hooks"),
            timeout=payload.get("timeout", 120),
            default_model=payload.get("default_model"),
            default_channel=payload.get("default_channel", "last"),
        )
        set_openclaw_config(openclaw_config)
        Modules.openclaw_client = get_openclaw_client()

        logger.info(f"OpenClaw 配置更新: {openclaw_config.gateway_url}")

        return {"success": True, "message": "OpenClaw 配置已更新", "gateway_url": openclaw_config.gateway_url}
    except Exception as e:
        logger.error(f"OpenClaw 配置失败: {e}")
        raise HTTPException(500, f"配置失败: {e}")


@app.post("/openclaw/send")
async def openclaw_send_message(payload: Dict[str, Any]):
    """
    发送消息给 OpenClaw Agent

    使用 POST /hooks/agent 端点
    文档: https://docs.openclaw.ai/automation/webhook

    请求体:
    - message: 消息内容 (必需)
    - task_id: 外部任务ID（可选；用于与调度器task_id对齐）
    - session_key: 会话标识 (可选)
    - name: hook 名称 (可选)
    - channel: 消息通道 (可选)
    - to: 接收者 (可选)
    - model: 模型名称 (可选)
    - wake_mode: 唤醒模式 now/next-heartbeat (可选)
    - deliver: 是否投递 (可选)
    - timeout_seconds: 等待结果超时时间，默认120秒 (可选)
    """
    if not Modules.openclaw_client:
        raise HTTPException(503, "OpenClaw 客户端未就绪")

    message = payload.get("message")
    if not message:
        raise HTTPException(400, "message 不能为空")

    # 如果提供了 task_id 但未提供 session_key，则默认使用 task_id 派生稳定会话键，便于按任务查看中间过程
    task_id = payload.get("task_id")
    session_key = payload.get("session_key")
    if task_id and not session_key:
        session_key = f"naga:task:{task_id}"

    try:
        task = await Modules.openclaw_client.send_message(
            message=message,
            session_key=session_key,
            name=payload.get("name"),
            channel=payload.get("channel"),
            to=payload.get("to"),
            model=payload.get("model"),
            wake_mode=payload.get("wake_mode", "now"),
            deliver=payload.get("deliver", False),
            timeout_seconds=payload.get("timeout_seconds", 120),
            task_id=task_id,
        )

        return {
            "success": task.status.value != "failed",
            "task": task.to_dict(),
            "reply": task.result.get("reply") if task.result else None,
            "replies": task.result.get("replies") if task.result else None,
            "error": task.error,
        }
    except Exception as e:
        logger.error(f"OpenClaw 发送消息失败: {e}")
        raise HTTPException(500, f"发送失败: {e}")


@app.post("/openclaw/wake")
async def openclaw_wake(payload: Dict[str, Any]):
    """
    触发 OpenClaw 系统事件

    使用 POST /hooks/wake 端点
    文档: https://docs.openclaw.ai/automation/webhook

    请求体:
    - text: 事件描述 (必需)
    - mode: 触发模式 now/next-heartbeat (可选)
    """
    if not Modules.openclaw_client:
        raise HTTPException(503, "OpenClaw 客户端未就绪")

    text = payload.get("text")
    if not text:
        raise HTTPException(400, "text 不能为空")

    try:
        result = await Modules.openclaw_client.wake(text=text, mode=payload.get("mode", "now"))
        return result
    except Exception as e:
        logger.error(f"OpenClaw 触发事件失败: {e}")
        raise HTTPException(500, f"触发失败: {e}")


@app.post("/openclaw/tools/invoke")
async def openclaw_invoke_tool(payload: Dict[str, Any]):
    """
    直接调用 OpenClaw 工具

    使用 POST /tools/invoke 端点
    文档: https://docs.openclaw.ai/gateway/tools-invoke-http-api

    请求体:
    - tool: 工具名称 (必需)
    - args: 工具参数 (可选)
    - action: 动作 (可选)
    - session_key: 会话标识 (可选)
    """
    if not Modules.openclaw_client:
        raise HTTPException(503, "OpenClaw 客户端未就绪")

    tool = payload.get("tool")
    if not tool:
        raise HTTPException(400, "tool 不能为空")

    try:
        result = await Modules.openclaw_client.invoke_tool(
            tool=tool, args=payload.get("args"), action=payload.get("action"), session_key=payload.get("session_key")
        )
        return result
    except Exception as e:
        logger.error(f"OpenClaw 工具调用失败: {e}")
        raise HTTPException(500, f"调用失败: {e}")


# ============ OpenClaw 本地任务查询 API ============


@app.get("/openclaw/tasks")
async def openclaw_get_local_tasks():
    """获取本地缓存的所有 OpenClaw 任务"""
    if not Modules.openclaw_client:
        raise HTTPException(503, "OpenClaw 客户端未就绪")

    try:
        tasks = Modules.openclaw_client.get_all_tasks()
        return {"success": True, "tasks": [task.to_dict() for task in tasks], "count": len(tasks)}
    except Exception as e:
        logger.error(f"获取 OpenClaw 任务失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.get("/openclaw/tasks/{task_id}")
async def openclaw_get_task(task_id: str):
    """获取单个 OpenClaw 任务"""
    if not Modules.openclaw_client:
        raise HTTPException(503, "OpenClaw 客户端未就绪")

    try:
        task = Modules.openclaw_client.get_task(task_id)
        if task:
            return {"success": True, "task": task.to_dict()}
        else:
            raise HTTPException(404, f"任务不存在: {task_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 OpenClaw 任务失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.get("/openclaw/tasks/{task_id}/detail")
async def openclaw_get_task_detail(
    task_id: str,
    include_history: bool = True,
    history_limit: int = 50,
    include_tools: bool = False,
):
    """获取单个 OpenClaw 任务详情（包含本地 events 与可选 sessions_history）"""
    if not Modules.openclaw_client:
        raise HTTPException(503, "OpenClaw 客户端未就绪")

    try:
        task = Modules.openclaw_client.get_task(task_id)
        if not task:
            raise HTTPException(404, f"任务不存在: {task_id}")

        resp: Dict[str, Any] = {
            "success": True,
            "task": task.to_dict(),
        }

        if include_history:
            if task.session_key:
                history = await Modules.openclaw_client.get_sessions_history(
                    session_key=task.session_key,
                    limit=history_limit,
                    include_tools=include_tools,
                )
                resp["history"] = history
            else:
                resp["history"] = {"success": True, "messages": [], "note": "task_has_no_session_key"}

        return resp
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 OpenClaw 任务详情失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.delete("/openclaw/tasks/completed")
async def openclaw_clear_completed_tasks():
    """清理已完成的 OpenClaw 任务"""
    if not Modules.openclaw_client:
        raise HTTPException(503, "OpenClaw 客户端未就绪")

    try:
        Modules.openclaw_client.clear_completed_tasks()
        return {"success": True, "message": "已清理完成的任务"}
    except Exception as e:
        logger.error(f"清理 OpenClaw 任务失败: {e}")
        raise HTTPException(500, f"清理失败: {e}")


@app.get("/openclaw/session")
async def openclaw_get_session():
    """
    获取当前 OpenClaw 调度终端会话信息

    用于在设置界面显示 Naga 调度 OpenClaw 的终端连接状态

    返回:
    - 有活跃会话: session_key, created_at, last_activity, message_count, last_run_id, status
    - 无会话: has_session=False, message="请和 OpenClaw 交互以显示交互终端"
    """
    if not Modules.openclaw_client:
        raise HTTPException(503, "OpenClaw 客户端未就绪")

    try:
        session_info = Modules.openclaw_client.get_session_info()

        if session_info is None:
            return {"has_session": False, "message": "请和 OpenClaw 交互以显示交互终端"}

        return {"has_session": True, "session": session_info}
    except Exception as e:
        logger.error(f"获取 OpenClaw 会话信息失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.get("/openclaw/history")
async def openclaw_get_history(session_key: Optional[str] = None, limit: int = 20):
    """
    获取 OpenClaw 会话历史消息

    用于在设置界面显示 OpenClaw Agent 的对话内容

    Args:
        session_key: 会话标识，不传则使用默认会话
        limit: 返回消息条数限制

    Returns:
        会话历史消息列表
    """
    if not Modules.openclaw_client:
        raise HTTPException(503, "OpenClaw 客户端未就绪")

    try:
        result = await Modules.openclaw_client.get_sessions_history(session_key=session_key, limit=limit)
        return result
    except Exception as e:
        logger.error(f"获取 OpenClaw 会话历史失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.get("/openclaw/status")
async def openclaw_get_status():
    """
    获取 OpenClaw 当前状态

    调用 session_status 工具获取实时状态

    Returns:
        OpenClaw 当前状态文本
    """
    if not Modules.openclaw_client:
        raise HTTPException(503, "OpenClaw 客户端未就绪")

    try:
        result = await Modules.openclaw_client.get_session_status()
        return result
    except Exception as e:
        logger.error(f"获取 OpenClaw 状态失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


# ============ OpenClaw 安装和配置管理 API ============


@app.get("/openclaw/install/check")
async def openclaw_check_installation():
    """
    检查 OpenClaw 安装状态

    Returns:
        安装状态信息
    """
    try:
        from agentserver.openclaw import get_openclaw_installer

        installer = get_openclaw_installer()
        status, version = installer.check_installation()

        # 检查 Node.js
        node_ok, node_version = installer.check_node_version()

        return {
            "success": True,
            "status": status.value,
            "version": version,
            "node_ok": node_ok,
            "node_version": node_version,
            "npm_available": installer.check_npm_available(),
        }
    except Exception as e:
        logger.error(f"检查 OpenClaw 安装状态失败: {e}")
        raise HTTPException(500, f"检查失败: {e}")


@app.post("/openclaw/install")
async def openclaw_install(payload: Dict[str, Any] = None):
    """
    安装 OpenClaw

    请求体:
    - method: 安装方式 ("npm" 或 "script"，默认 "npm")

    Returns:
        安装结果
    """
    try:
        from agentserver.openclaw import get_openclaw_installer, InstallMethod

        installer = get_openclaw_installer()

        method_str = (payload or {}).get("method", "npm")
        method = InstallMethod.NPM if method_str == "npm" else InstallMethod.SCRIPT

        result = await installer.install(method)

        return result.to_dict()
    except Exception as e:
        logger.error(f"安装 OpenClaw 失败: {e}")
        raise HTTPException(500, f"安装失败: {e}")


@app.post("/openclaw/setup")
async def openclaw_setup(payload: Dict[str, Any] = None):
    """
    初始化 OpenClaw 配置

    请求体:
    - hooks_token: Hooks 认证 token（可选，不传则自动生成）

    Returns:
        初始化结果
    """
    try:
        from agentserver.openclaw import get_openclaw_installer

        installer = get_openclaw_installer()
        hooks_token = (payload or {}).get("hooks_token")

        result = await installer.setup(hooks_token)

        return result.to_dict()
    except Exception as e:
        logger.error(f"初始化 OpenClaw 失败: {e}")
        raise HTTPException(500, f"初始化失败: {e}")


@app.post("/openclaw/gateway/start")
async def openclaw_start_gateway():
    """启动 OpenClaw Gateway"""
    try:
        from agentserver.openclaw import get_openclaw_installer

        installer = get_openclaw_installer()
        result = await installer.start_gateway(background=True)

        return result.to_dict()
    except Exception as e:
        logger.error(f"启动 Gateway 失败: {e}")
        raise HTTPException(500, f"启动失败: {e}")


@app.post("/openclaw/gateway/stop")
async def openclaw_stop_gateway():
    """停止 OpenClaw Gateway"""
    try:
        from agentserver.openclaw import get_openclaw_installer

        installer = get_openclaw_installer()
        result = await installer.stop_gateway()

        return result.to_dict()
    except Exception as e:
        logger.error(f"停止 Gateway 失败: {e}")
        raise HTTPException(500, f"停止失败: {e}")


@app.post("/openclaw/gateway/restart")
async def openclaw_restart_gateway():
    """重启 OpenClaw Gateway"""
    try:
        from agentserver.openclaw import get_openclaw_installer

        installer = get_openclaw_installer()
        result = await installer.restart_gateway()

        return result.to_dict()
    except Exception as e:
        logger.error(f"重启 Gateway 失败: {e}")
        raise HTTPException(500, f"重启失败: {e}")


@app.post("/openclaw/gateway/install")
async def openclaw_install_gateway_service():
    """安装 Gateway 为系统服务"""
    try:
        from agentserver.openclaw import get_openclaw_installer

        installer = get_openclaw_installer()
        result = await installer.install_gateway_service()

        return result.to_dict()
    except Exception as e:
        logger.error(f"安装 Gateway 服务失败: {e}")
        raise HTTPException(500, f"安装失败: {e}")


@app.get("/openclaw/gateway/status")
async def openclaw_gateway_status():
    """获取 Gateway 状态"""
    try:
        from agentserver.openclaw import get_openclaw_installer

        installer = get_openclaw_installer()
        result = await installer.check_gateway_status()

        return result
    except Exception as e:
        logger.error(f"获取 Gateway 状态失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.get("/openclaw/doctor")
async def openclaw_doctor():
    """运行 OpenClaw 健康检查"""
    try:
        from agentserver.openclaw import get_openclaw_installer

        installer = get_openclaw_installer()
        result = await installer.run_doctor()

        return result
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        raise HTTPException(500, f"检查失败: {e}")


# ============ OpenClaw 配置管理 API ============


@app.get("/openclaw/config")
async def openclaw_get_config():
    """
    获取 OpenClaw 配置摘要

    只返回安全的配置信息，不包含 token 等敏感数据
    """
    try:
        from agentserver.openclaw import get_openclaw_config_manager

        config_manager = get_openclaw_config_manager()
        summary = config_manager.get_current_config_summary()

        return {"success": True, "config": summary}
    except Exception as e:
        logger.error(f"获取 OpenClaw 配置失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.post("/openclaw/config/set")
async def openclaw_set_config(payload: Dict[str, Any]):
    """
    设置 OpenClaw 配置

    只允许修改白名单中的字段

    请求体:
    - field: 字段路径（如 "agents.defaults.model.primary"）
    - value: 新值

    Returns:
        更新结果
    """
    try:
        from agentserver.openclaw import get_openclaw_config_manager

        field = payload.get("field")
        value = payload.get("value")

        if not field:
            raise HTTPException(400, "field 不能为空")

        config_manager = get_openclaw_config_manager()
        result = config_manager.set(field, value)

        return result.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"设置 OpenClaw 配置失败: {e}")
        raise HTTPException(500, f"设置失败: {e}")


@app.post("/openclaw/config/model")
async def openclaw_set_model(payload: Dict[str, Any]):
    """
    设置默认模型

    请求体:
    - model: 模型标识符（如 "zai/glm-4.7"）
    - alias: 模型别名（可选）

    Returns:
        更新结果
    """
    try:
        from agentserver.openclaw import get_openclaw_config_manager

        model = payload.get("model")
        alias = payload.get("alias")

        if not model:
            raise HTTPException(400, "model 不能为空")

        config_manager = get_openclaw_config_manager()

        results = []

        # 设置主模型
        result = config_manager.set_primary_model(model)
        results.append(result.to_dict())

        # 设置别名（如果提供）
        if alias:
            alias_result = config_manager.add_model_alias(model, alias)
            results.append(alias_result.to_dict())

        return {"success": all(r["success"] for r in results), "results": results}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"设置模型失败: {e}")
        raise HTTPException(500, f"设置失败: {e}")


@app.post("/openclaw/config/hooks")
async def openclaw_configure_hooks(payload: Dict[str, Any]):
    """
    配置 Hooks

    请求体:
    - enabled: 是否启用（可选）
    - token: Hooks token（可选，不传则自动生成）

    Returns:
        更新结果
    """
    try:
        from agentserver.openclaw import get_openclaw_config_manager

        config_manager = get_openclaw_config_manager()
        results = []

        # 启用/禁用
        if "enabled" in payload:
            result = config_manager.set_hooks_enabled(payload["enabled"])
            results.append(result.to_dict())

        # 设置 token
        if "token" in payload:
            token = payload["token"]
        elif payload.get("generate_token"):
            token = config_manager.generate_hooks_token()
        else:
            token = None

        if token:
            result = config_manager.set_hooks_token(token)
            results.append(result.to_dict())

        return {
            "success": all(r["success"] for r in results) if results else True,
            "results": results,
            "token": token,  # 返回生成的 token
        }
    except Exception as e:
        logger.error(f"配置 Hooks 失败: {e}")
        raise HTTPException(500, f"配置失败: {e}")


# ============ OpenClaw Skills 管理 API ============


@app.get("/openclaw/skills")
async def openclaw_list_skills():
    """列出已安装的 Skills"""
    try:
        from agentserver.openclaw import get_openclaw_installer

        installer = get_openclaw_installer()
        skills = await installer.list_skills()

        return {"success": True, "skills": skills}
    except Exception as e:
        logger.error(f"列出 Skills 失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.post("/openclaw/skills/install")
async def openclaw_install_skill(payload: Dict[str, Any]):
    """
    安装 Skill

    请求体:
    - skill: Skill 标识符

    Returns:
        安装结果
    """
    try:
        from agentserver.openclaw import get_openclaw_installer

        skill = payload.get("skill")
        if not skill:
            raise HTTPException(400, "skill 不能为空")

        installer = get_openclaw_installer()
        result = await installer.install_skill(skill)

        return result.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"安装 Skill 失败: {e}")
        raise HTTPException(500, f"安装失败: {e}")


@app.post("/openclaw/skills/enable")
async def openclaw_enable_skill(payload: Dict[str, Any]):
    """
    启用/禁用 Skill

    请求体:
    - skill: Skill 名称
    - enabled: 是否启用

    Returns:
        更新结果
    """
    try:
        from agentserver.openclaw import get_openclaw_config_manager

        skill = payload.get("skill")
        enabled = payload.get("enabled", True)

        if not skill:
            raise HTTPException(400, "skill 不能为空")

        config_manager = get_openclaw_config_manager()
        result = config_manager.enable_skill(skill, enabled)

        return result.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启用/禁用 Skill 失败: {e}")
        raise HTTPException(500, f"操作失败: {e}")


# ============ 旅行执行 ============

@app.post("/travel/execute")
async def travel_execute(payload: Dict[str, Any]):
    """接收旅行 session_id，异步启动旅行协程"""
    session_id = payload.get("session_id")
    if not session_id:
        raise HTTPException(400, "session_id 不能为空")

    if not Modules.openclaw_client:
        raise HTTPException(503, "OpenClaw 客户端未就绪")

    asyncio.create_task(_run_travel_session(session_id))
    return {"status": "accepted", "session_id": session_id}


async def _run_travel_session(session_id: str):
    """旅行主循环协程"""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from apiserver.travel_service import (
        load_session, save_session, TravelStatus,
        build_travel_prompt, build_social_prompt,
        parse_discoveries, parse_social,
    )

    try:
        session = load_session(session_id)
    except FileNotFoundError:
        logger.error(f"旅行 session 不存在: {session_id}")
        return

    session_key = f"travel:{session_id[:12]}"
    session.openclaw_session_key = session_key
    session.status = TravelStatus.RUNNING
    session.started_at = datetime.now().isoformat()
    save_session(session)

    logger.info(f"[旅行] 开始旅行 session: {session_id}, key={session_key}")

    try:
        # 发送探索指令
        await Modules.openclaw_client.send_message(
            message=build_travel_prompt(session),
            session_key=session_key,
            name="NagaTravel",
            timeout_seconds=0,
        )

        # 如果想社交，额外发送社交指令
        if session.want_friends:
            await Modules.openclaw_client.send_message(
                message=build_social_prompt(session),
                session_key=session_key,
                name="NagaTravel",
                timeout_seconds=0,
            )

        # 监控循环
        start_time = datetime.fromisoformat(session.started_at)
        seen_discovery_urls: set = set()
        seen_social_keys: set = set()

        while True:
            await asyncio.sleep(60)

            # 检查时间限制
            elapsed = (datetime.now() - start_time).total_seconds() / 60
            session.elapsed_minutes = round(elapsed, 1)

            if elapsed >= session.time_limit_minutes:
                logger.info(f"[旅行] 时间到达限制 {session.time_limit_minutes} 分钟")
                break

            # 重新加载 session（可能被外部 cancel）
            try:
                session = load_session(session_id)
            except Exception:
                break

            if session.status == TravelStatus.CANCELLED:
                logger.info(f"[旅行] session 已被取消: {session_id}")
                return

            # 轮询 OpenClaw 获取新消息
            try:
                history = await Modules.openclaw_client.get_sessions_history(
                    session_key=session_key, limit=50, include_tools=False,
                )
                messages = history if isinstance(history, list) else history.get("messages", [])

                # 解析发现和社交互动
                new_discoveries = parse_discoveries(messages)
                for d in new_discoveries:
                    if d.url not in seen_discovery_urls:
                        seen_discovery_urls.add(d.url)
                        session.discoveries.append(d)

                new_social = parse_social(messages)
                for s in new_social:
                    key = f"{s.type}:{s.post_id}:{s.content_preview[:30]}"
                    if key not in seen_social_keys:
                        seen_social_keys.add(key)
                        session.social_interactions.append(s)

            except Exception as e:
                logger.warning(f"[旅行] 轮询历史失败: {e}")

            session.elapsed_minutes = round(elapsed, 1)
            save_session(session)

        # 发送收尾指令
        logger.info(f"[旅行] 发送收尾指令: {session_id}")
        try:
            await Modules.openclaw_client.send_message(
                message="旅行时间到了，请总结你的发现。列出你访问过的最有趣的内容，以及任何社交互动。",
                session_key=session_key,
                name="NagaTravel",
                timeout_seconds=300,
            )

            # 等待并获取最终回复
            await asyncio.sleep(30)
            history = await Modules.openclaw_client.get_sessions_history(
                session_key=session_key, limit=5, include_tools=False,
            )
            messages = history if isinstance(history, list) else history.get("messages", [])
            # 最后一条 assistant 消息作为 summary
            for msg in reversed(messages):
                role = msg.get("role", "")
                if role == "assistant":
                    session.summary = msg.get("content", "")[:2000]
                    break
        except Exception as e:
            logger.warning(f"[旅行] 收尾指令失败: {e}")
            session.summary = f"旅行完成，共发现 {len(session.discoveries)} 个内容。（收尾指令超时）"

        session.status = TravelStatus.COMPLETED
        session.completed_at = datetime.now().isoformat()
        save_session(session)

        logger.info(
            f"[旅行] 完成: {session_id}, 发现={len(session.discoveries)}, 社交={len(session.social_interactions)}"
        )

        # QQ 通知
        try:
            summary_text = session.summary or "旅行已完成"
            await Modules.openclaw_client.send_message(
                message=f"🌍 旅行报告\n{summary_text}\n\n发现了 {len(session.discoveries)} 个有趣内容。",
                channel="qq",
                deliver=True,
                session_key=session_key,
                name="NagaTravel",
                timeout_seconds=30,
            )
        except Exception as e:
            logger.warning(f"[旅行] QQ 通知发送失败: {e}")

    except Exception as e:
        logger.error(f"[旅行] 异常: {e}", exc_info=True)
        try:
            session = load_session(session_id)
            session.status = TravelStatus.FAILED
            session.error = str(e)
            session.completed_at = datetime.now().isoformat()
            save_session(session)
        except Exception:
            pass


# ========== Proactive Vision API ==========


@app.get("/proactive_vision/config")
async def get_proactive_vision_config():
    """获取主动视觉系统配置"""
    try:
        from agentserver.proactive_vision import load_proactive_config

        config = load_proactive_config()
        return {"success": True, "config": config.model_dump()}
    except Exception as e:
        logger.error(f"获取 ProactiveVision 配置失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.post("/proactive_vision/config")
async def update_proactive_vision_config(payload: Dict[str, Any]):
    """更新主动视觉系统配置"""
    try:
        from agentserver.proactive_vision import (
            load_proactive_config,
            save_proactive_config,
            ProactiveVisionConfig,
            replace_proactive_scheduler_async,
            create_proactive_analyzer,
        )

        # 加载当前配置并备份到内存（用于回滚）
        old_config_backup = load_proactive_config()

        # 更新字段
        config_dict = old_config_backup.model_dump()
        config_dict.update(payload)

        # 创建新配置对象并验证
        new_config = ProactiveVisionConfig(**config_dict)

        # 先保存配置，确保配置有效
        if not save_proactive_config(new_config):
            raise HTTPException(500, "配置保存失败")

        # 如果调度器已启动，需要重启以应用新配置
        if Modules.proactive_scheduler:
            was_running = Modules.proactive_scheduler._running

            try:
                # 使用线程安全的异步替换（会自动停止旧调度器）
                create_proactive_analyzer(new_config)
                Modules.proactive_scheduler = await replace_proactive_scheduler_async(new_config)

                # 如果配置启用且之前在运行，则启动新调度器
                if new_config.enabled and was_running:
                    await Modules.proactive_scheduler.start()
                elif new_config.enabled and not was_running:
                    # 如果配置启用但之前未运行，也启动
                    await Modules.proactive_scheduler.start()

            except Exception as e:
                logger.error(f"[ProactiveVision] 应用新配置失败: {e}")
                # 回滚：恢复旧配置（从内存备份）
                try:
                    save_proactive_config(old_config_backup)  # 恢复磁盘配置
                    create_proactive_analyzer(old_config_backup)
                    Modules.proactive_scheduler = await replace_proactive_scheduler_async(old_config_backup)
                    if was_running and old_config_backup.enabled:
                        await Modules.proactive_scheduler.start()
                    logger.info("[ProactiveVision] 已成功回滚到旧配置")
                except Exception as rollback_error:
                    logger.error(f"[ProactiveVision] 回滚失败: {rollback_error}")
                raise HTTPException(500, f"应用新配置失败，已尝试回滚: {e}")

        return {"success": True, "message": "配置已更新", "config": new_config.model_dump()}
    except Exception as e:
        logger.error(f"更新 ProactiveVision 配置失败: {e}")
        raise HTTPException(500, f"更新失败: {e}")


@app.post("/proactive_vision/enable")
async def enable_proactive_vision(payload: Dict[str, Any]):
    """启用/禁用主动视觉系统"""
    try:
        enabled = payload.get("enabled", True)

        from agentserver.proactive_vision import load_proactive_config, save_proactive_config

        config = load_proactive_config()
        config.enabled = enabled

        if save_proactive_config(config):
            if Modules.proactive_scheduler:
                if enabled:
                    await Modules.proactive_scheduler.start()
                else:
                    await Modules.proactive_scheduler.stop()

            status = "已启用" if enabled else "已禁用"
            return {"success": True, "message": f"主动视觉系统{status}", "enabled": enabled}
        else:
            raise HTTPException(500, "配置保存失败")
    except Exception as e:
        logger.error(f"切换 ProactiveVision 状态失败: {e}")
        raise HTTPException(500, f"操作失败: {e}")


@app.get("/proactive_vision/status")
async def get_proactive_vision_status():
    """获取主动视觉系统运行状态"""
    try:
        if not Modules.proactive_scheduler:
            return {
                "success": True,
                "running": False,
                "enabled": False,
                "message": "调度器未初始化",
            }

        from agentserver.proactive_vision import load_proactive_config, get_proactive_analyzer

        config = load_proactive_config()

        # 获取性能统计
        performance_stats = {}
        analyzer = get_proactive_analyzer()
        if analyzer:
            performance_stats = analyzer.get_performance_stats()

        return {
            "success": True,
            "running": Modules.proactive_scheduler._running,
            "enabled": config.enabled,
            "last_check": Modules.proactive_scheduler._last_check_time,
            "last_activity": Modules.proactive_scheduler._last_user_activity_time,
            "check_interval": config.check_interval_seconds,
            "performance": performance_stats,
        }
    except Exception as e:
        logger.error(f"获取 ProactiveVision 状态失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.post("/proactive_vision/trigger/test")
async def test_proactive_vision_trigger(payload: Dict[str, Any]):
    """测试触发规则（忽略冷却时间）"""
    try:
        rule_id = payload.get("rule_id")
        if not rule_id:
            raise HTTPException(400, "rule_id 不能为空")

        from agentserver.proactive_vision import load_proactive_config, get_proactive_trigger

        config = load_proactive_config()
        rule = None
        for r in config.trigger_rules:
            if r.rule_id == rule_id:
                rule = r
                break

        if not rule:
            raise HTTPException(404, f"规则不存在: {rule_id}")

        trigger = get_proactive_trigger()
        if not trigger:
            raise HTTPException(503, "触发器未初始化")

        # 重置冷却时间以允许立即触发
        trigger.reset_cooldown(rule_id)

        # 发送测试消息
        test_context = "这是一条测试消息"
        await trigger.send_proactive_message(rule, test_context)

        return {"success": True, "message": f"测试触发规则: {rule.name}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"测试 ProactiveVision 触发失败: {e}")
        raise HTTPException(500, f"测试失败: {e}")


@app.post("/proactive_vision/activity")
async def update_user_activity():
    """更新用户活动时间（由前端定期调用）"""
    try:
        if Modules.proactive_scheduler:
            Modules.proactive_scheduler.update_user_activity()
        return {"success": True}
    except Exception as e:
        logger.error(f"更新用户活动时间失败: {e}")
        return {"success": False, "error": str(e)}


@app.post("/proactive_vision/window_mode")
async def set_proactive_vision_window_mode(payload: Dict[str, Any]):
    """设置窗口模式（由前端在模式切换时调用）

    ProactiveVision只在悬浮球模式（ball/compact/full）下运行，classic模式时暂停

    Args:
        payload: {"mode": "classic" | "ball" | "compact" | "full"}
    """
    try:
        mode = payload.get("mode", "classic")

        if mode not in ("classic", "ball", "compact", "full"):
            return {"success": False, "error": f"无效的窗口模式: {mode}"}

        if Modules.proactive_scheduler:
            Modules.proactive_scheduler.set_window_mode(mode)

        return {
            "success": True,
            "mode": mode,
            "active": mode in ("ball", "compact", "full"),
        }
    except Exception as e:
        logger.error(f"设置窗口模式失败: {e}")
        return {"success": False, "error": str(e)}


@app.post("/proactive_vision/reset_timer")
async def reset_proactive_vision_timer(payload: Dict[str, Any]):
    """重置ProactiveVision检查计时器（由MCP Server调用）

    当AI主动调用screen_vision MCP时，MCP Server会调用此API重置计时器，
    避免ProactiveVision短时间内重复分析同一屏幕。

    Args:
        payload: {"reason": "mcp_call_screen_vision"}
    """
    try:
        reason = payload.get("reason", "external_trigger")

        if Modules.proactive_scheduler:
            Modules.proactive_scheduler.reset_check_timer(reason)
            return {
                "success": True,
                "message": "计时器已重置",
                "reason": reason,
            }
        else:
            return {
                "success": False,
                "error": "ProactiveVision调度器未初始化",
            }
    except Exception as e:
        logger.error(f"重置ProactiveVision计时器失败: {e}")
        return {"success": False, "error": str(e)}


@app.get("/proactive_vision/metrics")
async def get_proactive_vision_metrics():
    """获取ProactiveVision性能指标"""
    try:
        from agentserver.proactive_vision.metrics import get_metrics

        metrics = get_metrics()
        all_metrics = metrics.get_all_metrics()

        return {
            "success": True,
            "metrics": all_metrics,
        }
    except Exception as e:
        logger.error(f"获取 ProactiveVision metrics 失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


@app.get("/proactive_vision/metrics/prometheus")
async def get_proactive_vision_metrics_prometheus():
    """获取Prometheus格式的性能指标"""
    try:
        from agentserver.proactive_vision.metrics import get_metrics
        from fastapi.responses import PlainTextResponse

        metrics = get_metrics()
        prometheus_text = metrics.get_prometheus_format()

        return PlainTextResponse(content=prometheus_text, media_type="text/plain; version=0.0.4")
    except Exception as e:
        logger.error(f"获取 Prometheus metrics 失败: {e}")
        raise HTTPException(500, f"获取失败: {e}")


if __name__ == "__main__":
    import uvicorn
    from agentserver.config import AGENT_SERVER_PORT

    uvicorn.run(app, host="0.0.0.0", port=AGENT_SERVER_PORT, access_log=False)
