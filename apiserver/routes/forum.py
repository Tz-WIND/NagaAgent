"""娜迦网络论坛代理路由"""

import logging
from typing import Dict, Optional, Any

from fastapi import APIRouter, HTTPException, Request

from system.config import get_config
from apiserver import naga_auth

logger = logging.getLogger(__name__)

router = APIRouter()


async def _call_nagabusiness(
    method: str,
    path: str,
    request: Request = None,
    json_body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout_seconds: float = 15.0,
) -> Any:
    """代理请求到 NagaBusiness 服务器，支持服务端 token 自动刷新"""
    import httpx

    cfg = get_config()
    base_url = cfg.naga_business.forum_api_url.rstrip("/")
    url = f"{base_url}{path}"

    # 优先使用后端维护的 token（由 naga_auth 统一管理，保持最新）
    # 回退到前端传入的 token
    token = naga_auth.get_access_token()
    if not token and request:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]

    if not token:
        raise HTTPException(status_code=401, detail="未登录")

    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, trust_env=False) as client:
            resp = await client.request(method, url, params=params, json=json_body, headers=headers)

            # 401 时尝试服务端自动刷新 token 并重试一次
            if resp.status_code == 401 and naga_auth.has_refresh_token():
                logger.info("论坛代理收到 401，尝试服务端刷新 token...")
                try:
                    refresh_result = await naga_auth.refresh()
                    new_token = refresh_result.get("access_token")
                    if new_token:
                        headers["Authorization"] = f"Bearer {new_token}"
                        resp = await client.request(method, url, params=params, json=json_body, headers=headers)
                        logger.info(f"论坛代理刷新 token 后重试: {resp.status_code}")
                except Exception as e:
                    logger.warning(f"论坛代理刷新 token 失败: {e}")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"NagaBusiness 不可达: {e}")

    if resp.status_code >= 400:
        detail = resp.text
        try:
            detail = resp.json()
        except Exception:
            pass
        raise HTTPException(status_code=resp.status_code, detail=detail)

    return resp.json()


@router.get("/forum/api/posts")
async def forum_get_posts(request: Request):
    return await _call_nagabusiness("GET", "/v1/forum/posts", request, params=dict(request.query_params))


@router.get("/forum/api/posts/{post_id}")
async def forum_get_post(post_id: str, request: Request):
    return await _call_nagabusiness("GET", f"/v1/forum/posts/{post_id}", request)


@router.post("/forum/api/posts")
async def forum_create_post(request: Request):
    body = await request.json()
    return await _call_nagabusiness("POST", "/v1/forum/posts", request, json_body=body)


@router.post("/forum/api/posts/{post_id}/like")
async def forum_like_post(post_id: str, request: Request):
    return await _call_nagabusiness("POST", f"/v1/forum/posts/{post_id}/like", request)


@router.post("/forum/api/posts/{post_id}/comments")
async def forum_create_comment(post_id: str, request: Request):
    body = await request.json()
    return await _call_nagabusiness("POST", f"/v1/forum/posts/{post_id}/comments", request, json_body=body)


@router.post("/forum/api/comments/{comment_id}/like")
async def forum_like_comment(comment_id: str, request: Request):
    return await _call_nagabusiness("POST", f"/v1/forum/comments/{comment_id}/like", request)


@router.get("/forum/api/profile")
async def forum_get_profile(request: Request):
    return await _call_nagabusiness("GET", "/v1/forum/profile", request)


@router.get("/forum/api/messages")
async def forum_get_messages(request: Request):
    return await _call_nagabusiness("GET", "/v1/forum/messages", request, params=dict(request.query_params))


@router.post("/forum/api/friend-request/{req_id}/accept")
async def forum_accept_friend(req_id: str, request: Request):
    return await _call_nagabusiness("POST", f"/v1/forum/friend-request/{req_id}/accept", request)


@router.post("/forum/api/friend-request/{req_id}/decline")
async def forum_decline_friend(req_id: str, request: Request):
    return await _call_nagabusiness("POST", f"/v1/forum/friend-request/{req_id}/decline", request)


@router.put("/forum/api/posts/{post_id}")
async def forum_update_post(post_id: str, request: Request):
    body = await request.json()
    return await _call_nagabusiness("PUT", f"/v1/forum/posts/{post_id}", request, json_body=body)


@router.delete("/forum/api/posts/{post_id}")
async def forum_delete_post(post_id: str, request: Request):
    return await _call_nagabusiness("DELETE", f"/v1/forum/posts/{post_id}", request)


@router.delete("/forum/api/comments/{comment_id}")
async def forum_delete_comment(comment_id: str, request: Request):
    return await _call_nagabusiness("DELETE", f"/v1/forum/comments/{comment_id}", request)


@router.get("/forum/api/comments")
async def forum_list_comments(request: Request):
    return await _call_nagabusiness("GET", "/v1/forum/comments", request, params=dict(request.query_params))


@router.get("/forum/api/boards")
async def forum_get_boards(request: Request):
    return await _call_nagabusiness("GET", "/v1/forum/boards", request)


@router.post("/forum/api/report")
async def forum_report(request: Request):
    body = await request.json()
    return await _call_nagabusiness("POST", "/v1/forum/report", request, json_body=body)


@router.get("/forum/api/friend-requests")
async def forum_get_friend_requests(request: Request):
    return await _call_nagabusiness("GET", "/v1/forum/friend-requests", request, params=dict(request.query_params))


@router.get("/forum/api/connections")
async def forum_get_connections(request: Request):
    return await _call_nagabusiness("GET", "/v1/forum/connections", request)


@router.post("/forum/api/messages")
async def forum_send_message(request: Request):
    body = await request.json()
    return await _call_nagabusiness("POST", "/v1/forum/messages", request, json_body=body)


@router.put("/forum/api/profile")
async def forum_update_profile(request: Request):
    body = await request.json()
    return await _call_nagabusiness("PUT", "/v1/forum/profile", request, json_body=body)


@router.get("/forum/api/notifications")
async def forum_get_notifications(request: Request):
    return await _call_nagabusiness("GET", "/v1/forum/notifications", request, params=dict(request.query_params))


@router.post("/forum/api/notifications/{notif_id}/read")
async def forum_mark_notification_read(notif_id: str, request: Request):
    return await _call_nagabusiness("POST", f"/v1/forum/notifications/{notif_id}/read", request)


@router.post("/forum/api/notifications/read-all")
async def forum_mark_all_notifications_read(request: Request):
    return await _call_nagabusiness("POST", "/v1/forum/notifications/read-all", request)
