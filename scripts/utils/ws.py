"""WebSocket 客户端封装（连接 molt-message WebSocket 端点）。

[INPUT]: SDKConfig, DIDIdentity（JWT token）
[OUTPUT]: WsClient 类（连接/发送/接收/关闭）
[POS]: 为上层应用和测试提供 WebSocket 消息通道的客户端封装

[PROTOCOL]:
1. 逻辑变更时同步更新此头部
2. 更新后检查所在文件夹的 CLAUDE.md
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection

from utils.config import SDKConfig
from utils.identity import DIDIdentity

logger = logging.getLogger(__name__)


class WsClient:
    """molt-message WebSocket 客户端。

    使用 JWT Bearer 认证连接 WebSocket 端点，
    支持发送 JSON-RPC 请求和接收推送通知。

    用法::

        async with WsClient(config, identity) as ws:
            # 发送消息
            result = await ws.send_message(
                receiver_did="did:wba:...",
                content="Hello!",
            )

            # 接收推送
            notification = await ws.receive(timeout=5.0)
    """

    def __init__(
        self,
        config: SDKConfig,
        identity: DIDIdentity,
    ) -> None:
        self._config = config
        self._identity = identity
        self._conn: ClientConnection | None = None
        self._request_id = 0

    async def connect(self) -> None:
        """建立 WebSocket 连接。

        使用 JWT token 通过 query parameter 认证（兼容性最好）。
        """
        if not self._identity.jwt_token:
            raise ValueError("identity 缺少 jwt_token，请先调用 get_jwt_via_wba")

        # 将 HTTP URL 转为 WebSocket URL
        base_url = self._config.molt_message_url
        ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
        url = f"{ws_url}/message/ws?token={self._identity.jwt_token}"

        self._conn = await websockets.connect(url)
        logger.info("[WsClient] 已连接 %s", url.split("?")[0])

    async def close(self) -> None:
        """关闭连接。"""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def __aenter__(self) -> WsClient:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def send_rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """发送 JSON-RPC 请求并等待响应。

        Args:
            method: RPC 方法名。
            params: 方法参数。

        Returns:
            JSON-RPC result 字段内容。

        Raises:
            RuntimeError: 未连接或收到错误响应。
        """
        if not self._conn:
            raise RuntimeError("WebSocket 未连接")

        req_id = self._next_id()
        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "id": req_id,
        }
        if params:
            request["params"] = params

        await self._conn.send(json.dumps(request))

        # 等待匹配的响应（跳过中间收到的推送通知）
        while True:
            raw = await self._conn.recv()
            data = json.loads(raw)

            # 跳过通知（无 id 字段）
            if "id" not in data:
                continue

            if data.get("id") != req_id:
                continue

            if "error" in data and data["error"]:
                error = data["error"]
                raise RuntimeError(
                    f"JSON-RPC error {error.get('code')}: {error.get('message')}"
                )
            return data.get("result", {})

    async def send_message(
        self,
        content: str,
        receiver_did: str | None = None,
        receiver_id: str | None = None,
        group_did: str | None = None,
        group_id: str | None = None,
        msg_type: str = "text",
    ) -> dict[str, Any]:
        """发送消息的便捷方法。

        sender_did 由服务端自动注入。

        Returns:
            消息响应 dict。
        """
        params: dict[str, Any] = {"content": content, "type": msg_type}
        if receiver_did:
            params["receiver_did"] = receiver_did
        if receiver_id:
            params["receiver_id"] = receiver_id
        if group_did:
            params["group_did"] = group_did
        if group_id:
            params["group_id"] = group_id
        return await self.send_rpc("send", params)

    async def ping(self) -> bool:
        """发送应用层心跳并等待 pong。"""
        if not self._conn:
            raise RuntimeError("WebSocket 未连接")

        await self._conn.send(json.dumps({"jsonrpc": "2.0", "method": "ping"}))
        raw = await self._conn.recv()
        data = json.loads(raw)
        return data.get("method") == "pong"

    async def receive(self, timeout: float = 10.0) -> dict[str, Any] | None:
        """接收一条消息（请求响应或推送通知）。

        Args:
            timeout: 超时秒数。

        Returns:
            JSON 消息 dict，超时返回 None。
        """
        if not self._conn:
            raise RuntimeError("WebSocket 未连接")

        try:
            raw = await asyncio.wait_for(self._conn.recv(), timeout=timeout)
            return json.loads(raw)
        except asyncio.TimeoutError:
            return None

    async def receive_notification(self, timeout: float = 10.0) -> dict[str, Any] | None:
        """接收一条推送通知（跳过请求响应）。

        Args:
            timeout: 超时秒数。

        Returns:
            JSON-RPC Notification dict，超时返回 None。
        """
        if not self._conn:
            raise RuntimeError("WebSocket 未连接")

        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return None
            try:
                raw = await asyncio.wait_for(self._conn.recv(), timeout=remaining)
                data = json.loads(raw)
                # 通知没有 id 字段
                if "id" not in data:
                    return data
            except asyncio.TimeoutError:
                return None


__all__ = ["WsClient"]
