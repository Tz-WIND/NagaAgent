"""系统信息、健康检查、配置、日志、更新路由"""

import asyncio
import logging
import traceback
from typing import Dict, Any

from fastapi import APIRouter, HTTPException

from system.config import get_config, VERSION, build_system_prompt
from system.config_manager import get_config_snapshot, update_config
from apiserver.message_manager import message_manager
from apiserver.api_server import SystemInfoResponse
from apiserver.telemetry import emit_telemetry

logger = logging.getLogger(__name__)

router = APIRouter()


def _notification_telemetry_snapshot(config_data: Dict[str, Any]) -> Dict[str, Any]:
    notifications = config_data.get("notifications", {}) or {}
    openclaw = config_data.get("openclaw", {}) or {}
    feishu_channel = openclaw.get("feishu", {}) or {}
    feishu_notify = notifications.get("feishu", {}) or {}
    qq_notify = notifications.get("qq", {}) or {}

    qq_target = str(qq_notify.get("binding_target") or "").strip()
    qq_code = str(qq_notify.get("email_verification_code") or "").strip()
    feishu_target = (
        str(feishu_notify.get("recipient_chat_id") or "").strip()
        if feishu_notify.get("recipient_type") == "chat_id"
        else str(feishu_notify.get("recipient_open_id") or "").strip()
    )

    return {
        "qq_enabled": bool(qq_notify.get("enabled")),
        "qq_has_binding": bool(qq_target),
        "qq_has_verification_code": bool(qq_code),
        "feishu_enabled": bool(feishu_notify.get("enabled")),
        "feishu_recipient_type": str(feishu_notify.get("recipient_type") or "open_id"),
        "feishu_has_target": bool(feishu_target),
        "feishu_has_app": bool(str(feishu_channel.get("app_id") or "").strip()) and bool(str(feishu_channel.get("app_secret") or "").strip()),
        "feishu_deliver_full_report": bool(feishu_notify.get("deliver_full_report", True)),
    }


# ============ 根路径 & 健康检查 ============


@router.get("/", response_model=Dict[str, str])
async def root():
    """API根路径"""
    return {
        "name": "NagaAgent API",
        "version": VERSION,
        "status": "running",
        "docs": "/docs",
    }


@router.get("/health")
async def health_check():
    """健康检查"""
    from apiserver.websocket_manager import get_websocket_manager

    ws_manager = get_websocket_manager()
    ws_stats = ws_manager.get_stats()

    return {
        "status": "healthy",
        "agent_ready": True,
        "websocket_connections": ws_stats["total_connections"],
        "timestamp": str(asyncio.get_running_loop().time()),
    }


@router.get("/health/full")
async def full_health_check():
    """完整健康检查（调用Agent Server的全面检查）"""
    import httpx
    from system.config import get_server_port

    agent_port = get_server_port("agent_server")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"http://127.0.0.1:{agent_port}/health/full")
            if resp.status_code == 200:
                return resp.json()
            else:
                raise HTTPException(resp.status_code, "Agent Server健康检查失败")
    except httpx.ConnectError:
        raise HTTPException(503, "无法连接到Agent Server")
    except Exception as e:
        raise HTTPException(500, f"健康检查失败: {e}")


# ============ 系统信息 & 配置 ============


@router.get("/system/info", response_model=SystemInfoResponse)
async def get_system_info():
    """获取系统信息"""

    return SystemInfoResponse(
        version=VERSION,
        status="running",
        available_services=[],  # MCP服务现在由mcpserver独立管理
        api_key_configured=bool(get_config().api.api_key and get_config().api.api_key != "sk-placeholder-key-not-set"),
    )


@router.get("/system/config")
async def get_system_config():
    """获取完整系统配置（web_live2d.model.source 由角色系统动态注入）"""
    try:
        config_data = get_config_snapshot()

        # 动态注入角色 Live2D 模型路径
        try:
            from system.config import load_character, CHARACTERS_DIR
            from urllib.parse import quote
            char_name = get_config().system.active_character
            char_data = load_character(char_name)
            port = get_config().api_server.port
            encoded_name = quote(char_name, safe="")
            encoded_model = quote(char_data["live2d_model"], safe="/")
            model_url = f"http://localhost:{port}/characters/{encoded_name}/{encoded_model}"
            config_data.setdefault("web_live2d", {}).setdefault("model", {})["source"] = model_url
        except Exception as char_err:
            logger.warning(f"角色模型路径注入失败: {char_err}")

        return {"status": "success", "config": config_data}
    except Exception as e:
        logger.error(f"获取系统配置失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@router.post("/system/config")
async def update_system_config(payload: Dict[str, Any]):
    """更新系统配置（自动过滤角色系统动态注入的 live2d 模型路径，避免写入 config.json）"""
    try:
        before_snapshot = get_config_snapshot()
        before_notification = _notification_telemetry_snapshot(before_snapshot)
        # 过滤掉由角色系统动态注入的 model.source，避免将 localhost URL 持久化
        web_live2d = payload.get("web_live2d", {})
        model_block = web_live2d.get("model", {})
        source = model_block.get("source", "")
        if source and "/characters/" in source and source.startswith("http://localhost"):
            model_block.pop("source", None)

        success = update_config(payload)
        if success:
            after_snapshot = get_config_snapshot()
            after_notification = _notification_telemetry_snapshot(after_snapshot)
            if after_notification != before_notification:
                emit_telemetry(
                    "notification_settings_updated",
                    {
                        "before": before_notification,
                        "after": after_notification,
                    },
                    source="apiserver",
                )
            return {"status": "success", "message": "配置更新成功"}
        else:
            raise HTTPException(status_code=500, detail="配置更新失败")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新系统配置失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")


@router.get("/system/prompt")
async def get_system_prompt(include_skills: bool = False):
    """获取系统提示词（默认只返回人格提示词，不包含技能列表）"""
    try:
        prompt = build_system_prompt()
        return {"status": "success", "prompt": prompt}
    except Exception as e:
        logger.error(f"获取系统提示词失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取系统提示词失败: {str(e)}")


@router.post("/system/prompt")
async def update_system_prompt(payload: Dict[str, Any]):
    """更新系统提示词"""
    try:
        content = payload.get("content")
        if not content:
            raise HTTPException(status_code=400, detail="缺少content参数")
        from system.config import save_prompt

        save_prompt("conversation_style_prompt", content)
        return {"status": "success", "message": "提示词更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新系统提示词失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"更新系统提示词失败: {str(e)}")


@router.get("/system/character")
async def get_active_character():
    """获取当前活跃角色信息及资源路径"""
    try:
        from system.config import load_character, CHARACTERS_DIR
        from urllib.parse import quote
        char_name = get_config().system.active_character
        char_data = load_character(char_name)
        port = get_config().api_server.port
        encoded_name = quote(char_name, safe="")
        encoded_model = quote(char_data["live2d_model"], safe="/")
        model_url = f"http://localhost:{port}/characters/{encoded_name}/{encoded_model}"
        return {
            "status": "success",
            "character": {
                "name": char_name,
                "ai_name": char_data["ai_name"],
                "user_name": char_data["user_name"],
                "live2d_model_url": model_url,
                "prompt_file": char_data["prompt_file"],
            },
        }
    except Exception as e:
        logger.error(f"获取角色信息失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取角色信息失败: {str(e)}")


@router.get("/system/characters")
async def list_characters():
    """列出所有角色模板"""
    try:
        from system.config import CHARACTERS_DIR, load_character
        from urllib.parse import quote

        active_name = get_config().system.active_character
        port = get_config().api_server.port
        characters = []
        if CHARACTERS_DIR.exists():
            for char_dir in sorted(CHARACTERS_DIR.iterdir()):
                if not char_dir.is_dir() or char_dir.name.startswith("."):
                    continue
                try:
                    data = load_character(char_dir.name)
                except Exception as char_err:
                    logger.warning(f"读取角色模板失败 [{char_dir.name}]: {char_err}")
                    continue

                characters.append({
                    "name": char_dir.name,
                    "ai_name": data.get("ai_name"),
                    "bio": data.get("bio"),
                    "voice": data.get("voice"),
                    "prompt_file": data.get("prompt_file"),
                    "portrait": data.get("portrait"),
                    "live2d_model": data.get("live2d_model"),
                    "live2d_model_url": (
                        f"http://localhost:{port}/characters/{quote(char_dir.name, safe='')}/{quote(data.get('live2d_model') or '', safe='/')}"
                        if data.get("live2d_model") else None
                    ),
                    "active": char_dir.name == active_name,
                })

        return {
            "status": "success",
            "active_character": active_name,
            "characters": characters,
        }
    except Exception as e:
        logger.error(f"获取角色模板列表失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取角色模板列表失败: {str(e)}")


# ============ 更新检查 ============


@router.get("/update/latest")
async def proxy_update_check(platform: str = "windows"):
    """代理更新检查请求，避免前端直接暴露服务器地址"""
    import httpx
    from apiserver import naga_auth
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{naga_auth.BUSINESS_URL}/api/app/NagaAgent/latest",
                params={"platform": platform},
            )
            if resp.status_code == 404:
                return {"has_update": False}
            resp.raise_for_status()
            data = resp.json()
            # 将相对下载路径拼成完整URL（已经是绝对URL则跳过）
            dl = data.get("download_url")
            if dl and not dl.startswith(("http://", "https://")):
                data["download_url"] = f"{naga_auth.BUSINESS_URL}{dl}"
            return data
    except Exception as e:
        logger.warning(f"更新检查失败: {e}")
        return {"has_update": False}


# ============ 日志上下文 ============


@router.get("/logs/context/statistics")
async def get_log_context_statistics(days: int = 7):
    """获取日志上下文统计信息"""
    try:
        statistics = message_manager.get_context_statistics(days)
        return {"status": "success", "statistics": statistics}
    except Exception as e:
        print(f"获取日志上下文统计错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")


@router.get("/logs/context/load")
async def load_log_context(days: int = 3, max_messages: int = None):
    """加载日志上下文"""
    try:
        messages = message_manager.load_recent_context(days=days, max_messages=max_messages)
        return {"status": "success", "messages": messages, "count": len(messages), "days": days}
    except Exception as e:
        print(f"加载日志上下文错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"加载上下文失败: {str(e)}")
