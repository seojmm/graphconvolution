"""
PlayMCP 클라이언트 래퍼.
- PlayMCP metadata에 따라 client_credentials + scope=default + resource=... 로 토큰 발급
- JSON-RPC 형태로 MCP endpoint를 호출
"""

import logging
import os
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests


logger = logging.getLogger(__name__)


class PlayMCPClient:
    def __init__(
        self,
        base_url: str,
        token_url: str,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        resource: str = "https://playmcp.kakao.com/mcp",
        scope: str = "default",
    ):
        self.base_url = base_url.rstrip("/")
        self.token_url = token_url
        self.client_id = client_id or os.getenv("PLAY_MCP_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("PLAY_MCP_CLIENT_SECRET")
        self.resource = resource
        self.scope = scope
        self._access_token: Optional[str] = None
        self._token_type: str = "Bearer"

        if not self.client_id or not self.client_secret:
            raise ValueError("PLAY_MCP_CLIENT_ID/SECRET must be set")

    def _ensure_token(self) -> str:
        if self._access_token:
            return self._access_token

        data = {
            "grant_type": "client_credentials",
            "scope": self.scope,
            "resource": self.resource,
        }

        logger.info("Requesting token from %s", self.token_url)
        resp = requests.post(
            self.token_url,
            data=data,
            auth=(self.client_id, self.client_secret),  # client_secret_basic
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=5,
        )

        if not resp.ok:
            logger.error(
                "Token request failed: %s %s\nBody: %s",
                resp.status_code,
                resp.reason,
                resp.text[:1000],
            )
            raise RuntimeError(f"Token request failed: {resp.status_code} {resp.reason}")

        content_type = resp.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            logger.error(
                "Token response is not JSON. Content-Type=%s, Body=%s",
                content_type,
                resp.text[:1000],
            )
            raise RuntimeError("Token response is not JSON")

        try:
            body = resp.json()
        except Exception:
            logger.error("Failed to parse token JSON. Raw body: %s", resp.text[:1000])
            raise

        access_token = body.get("access_token")
        token_type = body.get("token_type", "Bearer")
        if not access_token:
            logger.error("No access_token in token response: %s", body)
            raise RuntimeError("No access_token in token response")

        self._access_token = access_token
        self._token_type = token_type
        logger.info("Token acquired: type=%s", token_type)
        return self._access_token

    def call(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        token = self._ensure_token()
        headers = {
            "Authorization": f"{self._token_type} {token}",
            "Content-Type": "application/json",
        }
        payload = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": method,
            "params": params,
        }
        url = self.base_url
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        if not resp.ok:
            logger.error(
                "MCP call failed: %s %s\nBody: %s",
                resp.status_code,
                resp.reason,
                resp.text[:1000],
            )
            resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            logger.error(
                "MCP response is not JSON. Content-Type=%s, Body=%s",
                content_type,
                resp.text[:1000],
            )
            raise RuntimeError("MCP response is not JSON")
        return resp.json()
