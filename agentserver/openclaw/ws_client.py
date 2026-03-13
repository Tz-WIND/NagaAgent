#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenClaw WebSocket 客户端
参考官方 GatewayClient 实现，使用 WebSocket 协议与 Gateway 通信
"""

import asyncio
import json
import logging
import uuid
from typing import Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass
import websockets
from websockets.client import WebSocketClientProtocol

logger = logging.getLogger("openclaw.ws_client")

PROTOCOL_VERSION = 3


@dataclass
class ConnectParams:
    """WebSocket 连接参数"""
    token: Optional[str] = None
    clientName: str = "naga-agent"
    clientVersion: str = "5.1.0"
    mode: str = "local"
    minProtocol: int = PROTOCOL_VERSION
    maxProtocol: int = PROTOCOL_VERSION


class OpenClawWSClient:
    """OpenClaw WebSocket 客户端"""

    def __init__(
        self,
        gateway_url: str = "ws://127.0.0.1:20789",
        token: Optional[str] = None,
        on_event: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ):
        self.gateway_url = gateway_url.replace("http://", "ws://").replace("https://", "wss://")
        self.token = token
        self.on_event = on_event
        self.ws: Optional[WebSocketClientProtocol] = None
        self.pending: Dict[str, asyncio.Future] = {}
        self.seq = 0
        self.connected = False

    async def connect(self) -> bool:
        """建立 WebSocket 连接"""
        try:
            self.ws = await websockets.connect(self.gateway_url, max_size=10 * 1024 * 1024)

            # 发送 connect 帧
            connect_params = ConnectParams(token=self.token)
            await self._send_frame({
                "op": "connect",
                "params": {
                    "token": connect_params.token,
                    "clientName": connect_params.clientName,
                    "clientVersion": connect_params.clientVersion,
                    "mode": connect_params.mode,
                    "minProtocol": connect_params.minProtocol,
                    "maxProtocol": connect_params.maxProtocol,
                }
            })

            # 等待 hello 响应
            hello = await self._recv_frame()
            if hello.get("op") == "hello":
                self.connected = True
                logger.info(f"WebSocket 已连接: {hello}")

                # 启动接收循环
                asyncio.create_task(self._recv_loop())
                return True
            else:
                logger.error(f"连接失败: {hello}")
                return False

        except Exception as e:
            logger.error(f"WebSocket 连接失败: {e}")
            return False

    async def _send_frame(self, frame: Dict[str, Any]) -> None:
        """发送帧"""
        if not self.ws:
            raise RuntimeError("WebSocket 未连接")
        await self.ws.send(json.dumps(frame))

    async def _recv_frame(self) -> Dict[str, Any]:
        """接收帧"""
        if not self.ws:
            raise RuntimeError("WebSocket 未连接")
        data = await self.ws.recv()
        return json.loads(data)

    async def _recv_loop(self) -> None:
        """接收循环"""
        try:
            while self.connected and self.ws:
                frame = await self._recv_frame()
                await self._handle_frame(frame)
        except Exception as e:
            logger.error(f"接收循环异常: {e}")
            self.connected = False

    async def _handle_frame(self, frame: Dict[str, Any]) -> None:
        """处理接收到的帧"""
        op = frame.get("op")

        if op == "response":
            # 响应帧
            req_id = frame.get("id")
            if req_id and req_id in self.pending:
                future = self.pending.pop(req_id)
                if frame.get("ok"):
                    future.set_result(frame.get("result"))
                else:
                    future.set_exception(Exception(frame.get("error", {}).get("message", "Unknown error")))

        elif op == "event":
            # 事件帧
            if self.on_event:
                await self.on_event(frame.get("event", {}))

    async def chat_send(
        self,
        message: str,
        session_key: Optional[str] = None,
        agent_id: str = "main",
    ) -> str:
        """发送聊天消息"""
        req_id = str(uuid.uuid4())
        self.seq += 1

        future = asyncio.Future()
        self.pending[req_id] = future

        await self._send_frame({
            "op": "request",
            "id": req_id,
            "seq": self.seq,
            "method": "chat.send",
            "params": {
                "agentId": agent_id,
                "sessionKey": session_key or f"naga:{uuid.uuid4().hex[:8]}",
                "message": message,
            }
        })

        result = await asyncio.wait_for(future, timeout=120)
        return result

    async def close(self) -> None:
        """关闭连接"""
        self.connected = False
        if self.ws:
            await self.ws.close()
            self.ws = None
