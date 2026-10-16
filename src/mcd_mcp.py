"""麦当劳中国 MCP 客户端（Streamable HTTP / JSON-RPC 2.0）

仅负责协议层：初始化会话、列出工具、调用工具。
Token 只从环境变量 MCD_MCP_TOKEN 或显式入参读取，永不写入任何产出文件。
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import requests

DEFAULT_URL = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2025-06-18"


class McpError(RuntimeError):
    """MCP 协议或 HTTP 层错误。"""


class McpClient:
    def __init__(self, token: str | None = None, url: str = DEFAULT_URL, timeout: int = 30):
        self.url = url
        self.token = token or os.environ.get("MCD_MCP_TOKEN", "").strip()
        self.timeout = timeout
        self.session_id: str | None = None
        self.server_info: dict[str, Any] = {}
        self._http = requests.Session()
        self._initialized = False

    # ---------- 传输层 ----------
    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    @staticmethod
    def _decode(resp: requests.Response) -> dict[str, Any] | None:
        ctype = resp.headers.get("Content-Type", "")
        if "text/event-stream" in ctype:
            chunks = [ln[5:].strip() for ln in resp.text.splitlines() if ln.startswith("data:")]
            if not chunks:
                return None
            return json.loads(chunks[-1])
        if not resp.text.strip():
            return None
        return resp.json()

    def _post(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        resp = self._http.post(self.url, json=payload, headers=self._headers(), timeout=self.timeout)
        if resp.status_code == 401:
            raise McpError("401 未授权：MCP Token 无效、已过期或未提供")
        if resp.status_code == 429:
            raise McpError("429 限流：超过 600 次/分钟，请降低调用频率")
        if resp.status_code >= 400:
            raise McpError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        sid = resp.headers.get("Mcp-Session-Id")
        if sid:
            self.session_id = sid
        return self._decode(resp)

    def _rpc(self, method: str, params: dict[str, Any] | None = None, *, expect_response: bool = True):
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if expect_response:
            payload["id"] = uuid.uuid4().hex
        out = self._post(payload)
        if out is None:
            return None
        if "error" in out:
            err = out["error"]
            raise McpError(f"{method} 失败 [{err.get('code')}]: {err.get('message')}")
        return out.get("result")

    # ---------- 生命周期 ----------
    def initialize(self) -> dict[str, Any]:
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcd-order-ledger", "version": "1.0.0"},
            },
        )
        self.server_info = (result or {}).get("serverInfo", {})
        self._initialized = True
        self._rpc("notifications/initialized", expect_response=False)
        return result or {}

    def _ensure(self) -> None:
        if not self._initialized:
            self.initialize()

    # ---------- 能力 ----------
    def list_tools(self) -> list[dict[str, Any]]:
        self._ensure()
        result = self._rpc("tools/list") or {}
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """返回 {"text": 原始文本, "data": 结构化结果或 None, "is_error": bool}"""
        self._ensure()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}}) or {}
        blocks = result.get("content", []) or []
        text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        data = result.get("structuredContent")
        if data is None and text:
            data = _try_json(text)
        return {
            "text": text,
            "data": data,
            "is_error": bool(result.get("isError")),
        }


def _try_json(text: str):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def get_client(token: str | None = None) -> McpClient:
    client = McpClient(token=token)
    if not client.token:
        raise McpError(
            "未找到 MCP Token。请设置环境变量 MCD_MCP_TOKEN，或在项目根目录 .env 中配置。"
        )
    return client
