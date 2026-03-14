"""娜迦网络论坛代理路由"""

import logging
from typing import Callable, Dict, Optional, Any

from fastapi import APIRouter, HTTPException, Request

from system.config import get_config
from apiserver import naga_auth
from apiserver.telemetry import emit_telemetry

logger = logging.getLogger(__name__)

router = APIRouter()


def _emit_forum_telemetry(event: str, props: Dict[str, Any]) -> None:
    emit_telemetry(event, props, source="apiserver")


async def _call_forum_mutation(
    event_success: str,
    event_fail: str,
    props: Dict[str, Any],
    *,
    method: str,
    path: str,
    request: Optional[Request] = None,
    json_body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout_seconds: float = 15.0,
    on_success: Optional[Callable[[Any], Dict[str, Any]]] = None,
) -> Any:
    try:
        result = await _call_nagabusiness(
            method,
            path,
            request,
            json_body=json_body,
            params=params,
            timeout_seconds=timeout_seconds,
        )
    except HTTPException as exc:
        _emit_forum_telemetry(
            event_fail,
            {
                **props,
                "status_code": exc.status_code,
                "error": exc.detail,
            },
        )
        raise
    except Exception as exc:
        _emit_forum_telemetry(
            event_fail,
            {
                **props,
                "error": exc,
            },
        )
        raise

    success_props = dict(props)
    if on_success:
        try:
            success_props.update(on_success(result))
        except Exception as exc:
            logger.debug("论坛埋点成功补充字段失败: %s", exc)
    _emit_forum_telemetry(event_success, success_props)
    return result


def _build_non_json_detail(resp) -> dict[str, Any]:
    content_type = resp.headers.get("content-type", "")
    preview = (resp.text or "")[:300]
    return {
        "error": "upstream_non_json_response",
        "status_code": resp.status_code,
        "content_type": content_type,
        "body_preview": preview,
    }


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
    if not token and naga_auth.has_refresh_token():
        try:
            await naga_auth.ensure_access_token()
            token = naga_auth.get_access_token()
        except Exception as e:
            logger.warning(f"论坛代理预刷新 access token 失败: {e}")
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
                        logger.info(f"论坛代理刷新 token 后重试: {resp.status_code} url={url}")
                except Exception as e:
                    logger.warning(f"论坛代理刷新 token 失败: {e}")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"NagaBusiness 不可达: {e}")

    if resp.status_code >= 400:
        detail: Any
        content_type = resp.headers.get("content-type", "")
        if "json" in content_type.lower():
            try:
                detail = resp.json()
            except Exception:
                detail = _build_non_json_detail(resp)
        else:
            detail = _build_non_json_detail(resp)
        raise HTTPException(status_code=resp.status_code, detail=detail)

    try:
        return resp.json()
    except Exception:
        logger.warning(f"论坛代理上游返回非 JSON: url={url}, status={resp.status_code}")
        raise HTTPException(status_code=502, detail=_build_non_json_detail(resp))


async def create_forum_post_internal(
    payload: Dict[str, Any],
    timeout_seconds: float = 20.0,
) -> Any:
    """供服务端内部调用的发帖入口。"""
    return await _call_forum_mutation(
        "forum_post_create",
        "forum_post_create_fail",
        {
            "origin": "internal",
            "title_chars": len(str(payload.get("title") or "")),
            "content_chars": len(str(payload.get("content") or "")),
            "tag_count": len(payload.get("tags") or []),
            "image_count": len(payload.get("images") or []),
            "has_board_id": bool(payload.get("boardId") or payload.get("board_id")),
        },
        method="POST",
        path="/api/forum/posts",
        json_body=payload,
        timeout_seconds=timeout_seconds,
    )


@router.get("/forum/api/posts")
async def forum_get_posts(request: Request):
    return await _call_nagabusiness("GET", "/api/forum/posts", request, params=dict(request.query_params))


@router.get("/forum/api/posts/{post_id}")
async def forum_get_post(post_id: str, request: Request):
    return await _call_nagabusiness("GET", f"/api/forum/posts/{post_id}", request)


@router.post("/forum/api/posts")
async def forum_create_post(request: Request):
    body = await request.json()
    return await _call_forum_mutation(
        "forum_post_create",
        "forum_post_create_fail",
        {
            "title_chars": len(str(body.get("title") or "")),
            "content_chars": len(str(body.get("content") or "")),
            "tag_count": len(body.get("tags") or []),
            "image_count": len(body.get("images") or []),
            "has_board_id": bool(body.get("boardId") or body.get("board_id")),
        },
        method="POST",
        path="/api/forum/posts",
        request=request,
        json_body=body,
    )


@router.post("/forum/api/posts/{post_id}/like")
async def forum_like_post(post_id: str, request: Request):
    return await _call_forum_mutation(
        "forum_post_like",
        "forum_post_like_fail",
        {"post_id": post_id},
        method="POST",
        path=f"/api/forum/posts/{post_id}/like",
        request=request,
        on_success=lambda result: {
            "liked": bool(result.get("liked")) if isinstance(result, dict) and "liked" in result else None,
            "likes": result.get("likes") if isinstance(result, dict) else None,
        },
    )


@router.post("/forum/api/posts/{post_id}/comments")
async def forum_create_comment(post_id: str, request: Request):
    body = await request.json()
    return await _call_forum_mutation(
        "forum_comment_create",
        "forum_comment_create_fail",
        {
            "post_id": post_id,
            "content_chars": len(str(body.get("content") or "")),
            "has_parent_comment_id": bool(body.get("parentCommentId") or body.get("parent_comment_id")),
        },
        method="POST",
        path=f"/api/forum/posts/{post_id}/comments",
        request=request,
        json_body=body,
    )


@router.post("/forum/api/comments/{comment_id}/like")
async def forum_like_comment(comment_id: str, request: Request):
    return await _call_forum_mutation(
        "forum_comment_like",
        "forum_comment_like_fail",
        {"comment_id": comment_id},
        method="POST",
        path=f"/api/forum/comments/{comment_id}/like",
        request=request,
        on_success=lambda result: {
            "liked": bool(result.get("liked")) if isinstance(result, dict) and "liked" in result else None,
            "likes": result.get("likes") if isinstance(result, dict) else None,
        },
    )


@router.get("/forum/api/profile")
async def forum_get_profile(request: Request):
    return await _call_nagabusiness("GET", "/api/forum/profile", request)


@router.get("/forum/api/messages")
async def forum_get_messages(request: Request):
    return await _call_nagabusiness("GET", "/api/forum/messages", request, params=dict(request.query_params))


@router.post("/forum/api/friend-request/{req_id}/accept")
async def forum_accept_friend(req_id: str, request: Request):
    return await _call_forum_mutation(
        "forum_friend_accept",
        "forum_friend_accept_fail",
        {"request_id": req_id},
        method="POST",
        path=f"/api/forum/friend-request/{req_id}/accept",
        request=request,
    )


@router.post("/forum/api/friend-request/{req_id}/decline")
async def forum_decline_friend(req_id: str, request: Request):
    return await _call_forum_mutation(
        "forum_friend_decline",
        "forum_friend_decline_fail",
        {"request_id": req_id},
        method="POST",
        path=f"/api/forum/friend-request/{req_id}/decline",
        request=request,
    )


@router.put("/forum/api/posts/{post_id}")
async def forum_update_post(post_id: str, request: Request):
    body = await request.json()
    return await _call_forum_mutation(
        "forum_post_update",
        "forum_post_update_fail",
        {
            "post_id": post_id,
            "title_chars": len(str(body.get("title") or "")),
            "content_chars": len(str(body.get("content") or "")),
            "tag_count": len(body.get("tags") or []),
            "image_count": len(body.get("images") or []),
        },
        method="PUT",
        path=f"/api/forum/posts/{post_id}",
        request=request,
        json_body=body,
    )


@router.delete("/forum/api/posts/{post_id}")
async def forum_delete_post(post_id: str, request: Request):
    return await _call_forum_mutation(
        "forum_post_delete",
        "forum_post_delete_fail",
        {"post_id": post_id},
        method="DELETE",
        path=f"/api/forum/posts/{post_id}",
        request=request,
    )


@router.delete("/forum/api/comments/{comment_id}")
async def forum_delete_comment(comment_id: str, request: Request):
    return await _call_forum_mutation(
        "forum_comment_delete",
        "forum_comment_delete_fail",
        {"comment_id": comment_id},
        method="DELETE",
        path=f"/api/forum/comments/{comment_id}",
        request=request,
    )


@router.get("/forum/api/comments")
async def forum_list_comments(request: Request):
    return await _call_nagabusiness("GET", "/api/forum/comments", request, params=dict(request.query_params))


@router.get("/forum/api/boards")
async def forum_get_boards(request: Request):
    return await _call_nagabusiness("GET", "/api/forum/boards", request)


@router.post("/forum/api/report")
async def forum_report(request: Request):
    body = await request.json()
    return await _call_forum_mutation(
        "forum_report_submit",
        "forum_report_submit_fail",
        {
            "target_type": body.get("targetType") or body.get("target_type"),
            "target_id": body.get("targetId") or body.get("target_id"),
            "has_reason": bool(str(body.get("reason") or "").strip()),
            "description_chars": len(str(body.get("description") or "")),
        },
        method="POST",
        path="/api/forum/report",
        request=request,
        json_body=body,
    )


@router.get("/forum/api/friend-requests")
async def forum_get_friend_requests(request: Request):
    return await _call_nagabusiness("GET", "/api/forum/friend-requests", request, params=dict(request.query_params))


@router.get("/forum/api/connections")
async def forum_get_connections(request: Request):
    return await _call_nagabusiness("GET", "/api/forum/connections", request)


@router.post("/forum/api/messages")
async def forum_send_message(request: Request):
    body = await request.json()
    return await _call_forum_mutation(
        "forum_message_send",
        "forum_message_send_fail",
        {
            "content_chars": len(str(body.get("content") or "")),
            "has_post_id": bool(body.get("postId") or body.get("post_id")),
        },
        method="POST",
        path="/api/forum/messages",
        request=request,
        json_body=body,
    )


@router.put("/forum/api/profile")
async def forum_update_profile(request: Request):
    body = await request.json()
    return await _call_forum_mutation(
        "forum_profile_update",
        "forum_profile_update_fail",
        {
            "changed_fields": sorted(str(key) for key in body.keys())[:32],
            "bio_chars": len(str(body.get("bio") or "")),
            "has_avatar": bool(body.get("avatar")),
            "interest_count": len(body.get("interests") or []),
            "auto_evaluate": bool(body.get("autoEvaluate")) if "autoEvaluate" in body else None,
        },
        method="PUT",
        path="/api/forum/profile",
        request=request,
        json_body=body,
    )


@router.get("/forum/api/notifications")
async def forum_get_notifications(request: Request):
    return await _call_nagabusiness("GET", "/api/forum/notifications", request, params=dict(request.query_params))


@router.post("/forum/api/notifications/{notif_id}/read")
async def forum_mark_notification_read(notif_id: str, request: Request):
    return await _call_forum_mutation(
        "forum_notification_read",
        "forum_notification_read_fail",
        {"notification_id": notif_id},
        method="POST",
        path=f"/api/forum/notifications/{notif_id}/read",
        request=request,
    )


@router.post("/forum/api/notifications/read-all")
async def forum_mark_all_notifications_read(request: Request):
    return await _call_forum_mutation(
        "forum_notifications_read_all",
        "forum_notifications_read_all_fail",
        {},
        method="POST",
        path="/api/forum/notifications/read-all",
        request=request,
    )
