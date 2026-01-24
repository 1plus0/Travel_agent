from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx


class BaseMCPClient:
    def __init__(self, base_url: str):
        self.base_url = base_url

    def _try_parse_sse_json(self, text: str) -> Optional[Dict[str, Any]]:
        if not text or "data:" not in text:
            return None
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            raw = line[len("data:") :].strip()
            if not raw:
                continue
            try:
                return json.loads(raw)
            except Exception:
                return None
        return None

    def _extract_result_json(self, rpc_data: Dict[str, Any]) -> Any:
        if not isinstance(rpc_data, dict):
            return None
        result = rpc_data.get("result")
        if isinstance(result, dict) and isinstance(result.get("content"), list) and result["content"]:
            txt = result["content"][0].get("text")
            if isinstance(txt, str):
                try:
                    return json.loads(txt)
                except Exception:
                    return txt
        return result

    async def _rpc(self, method: str, params: Optional[Dict[str, Any]] = None, rpc_id: str = "1") -> Dict[str, Any]:
        if not self.base_url:
            return {"success": False, "error": "MCP base_url 未配置"}

        payload: Dict[str, Any] = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
        if params is not None:
            payload["params"] = params

        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
            resp = await client.post(self.base_url, json=payload, headers=headers)

            meta = {
                "status_code": resp.status_code,
                "content_type": resp.headers.get("content-type"),
                "content_length": resp.headers.get("content-length"),
                # 不回传 url，避免 api_key 泄露
                "payload": payload,
            }

            text = resp.text or ""
            if resp.status_code >= 400:
                return {"success": False, "error": f"HTTP {resp.status_code}", "raw": text, "meta": meta}

            try:
                data = resp.json()
            except Exception:
                data = self._try_parse_sse_json(text)

            if not isinstance(data, dict):
                return {"success": False, "error": "无法解析 MCP 响应", "raw": text, "meta": meta}

            if data.get("error"):
                return {"success": False, "error": str(data["error"]), "raw": data, "meta": meta}

            return {"success": True, "data": data, "meta": meta}

    async def list_tools(self) -> Dict[str, Any]:
        return await self._rpc("tools/list")

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return await self._rpc("tools/call", {"name": name, "arguments": arguments})