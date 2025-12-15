"""
PlayMCP 클라이언트 래퍼.
- PlayMCP metadata에 따라 OAuth 토큰을 확보한 뒤 JSON-RPC 형태로 MCP endpoint를 호출
"""

import logging
import os
import time
import uuid
import itertools
from typing import Any, Dict, Optional

import requests


logger = logging.getLogger(__name__)


class PlayMCPClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        token_url: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        resource: Optional[str] = None,
        scope: Optional[str] = None,
        tokens_file: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        self.base_url = (
            (base_url or os.getenv("PLAY_MCP_ENDPOINT") or os.getenv("PLAY_MCP_TOOLBOX_URL") or "").rstrip("/")
        )
        # 토큰 URL/클라이언트 정보는 선택 사항 (직접 발급 토큰 사용 시 불필요)
        self.token_url = token_url or os.getenv("PLAY_MCP_TOKEN_URL") or os.getenv("KAKAO_TOKEN_URL")
        self.client_id = client_id
        self.client_secret = client_secret
        self.resource = (
            resource
            or os.getenv("PLAY_MCP_ENDPOINT")
            or os.getenv("PLAY_MCP_TOOLBOX_URL")
            or self.base_url
        )
        self.scope = scope or os.getenv("PLAY_MCP_SCOPE") or os.getenv("KAKAO_SCOPE") or "talk_calendar"
        self.tokens_file = tokens_file or os.getenv("PLAY_MCP_TOKENS_FILE", ".kakao_oauth_tokens.json")
        # MCP Gateway 세션 ID (응답 헤더에서 받은 값을 저장)
        self.session_id = session_id or os.getenv("PLAY_MCP_SESSION_ID") or None

        self._tokens: Dict[str, Any] = {}
        self._initialized: bool = False
        self._req_id = itertools.count(start=1)

        if not self.base_url:
            raise ValueError("PLAY_MCP_ENDPOINT/PLAY_MCP_TOOLBOX_URL 설정이 필요합니다.")

        # 미리 파일에 저장된 토큰이 있으면 로드
        self._load_tokens()
        # 환경변수로 직접 토큰을 주입할 수 있게 허용
        env_token = os.getenv("PLAY_MCP_TOKEN")
        if env_token:
            self._tokens = {
                "access_token": env_token,
                "token_type": os.getenv("PLAY_MCP_TOKEN_TYPE", "Bearer"),
                "expires_at": None,
            }

    # ------------------------------------------------------------------
    # 토큰 관리
    # ------------------------------------------------------------------
    def _load_tokens(self) -> None:
        if os.path.exists(self.tokens_file):
            try:
                import json

                with open(self.tokens_file, encoding="utf-8") as f:
                    self._tokens = json.load(f)
            except Exception as e:
                logger.warning("Failed to load tokens file %s: %s", self.tokens_file, e)

    def _save_tokens(self) -> None:
        try:
            import json

            with open(self.tokens_file, "w", encoding="utf-8") as f:
                json.dump(self._tokens, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("Failed to save tokens file %s: %s", self.tokens_file, e)

    def _is_expired(self) -> bool:
        expires_at = self._tokens.get("expires_at")
        # expires_at 정보가 없으면 만료로 취급하지 않고 사용
        if expires_at is None:
            return False
        return time.time() >= expires_at

    def _refresh_token(self) -> str:
        refresh_token = self._tokens.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("No refresh_token available; please re-login via authorization_code flow.")
        if not self.token_url or not self.client_id:
            raise RuntimeError("Token refresh is not configured (missing token_url or client credentials).")

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": self.scope,
            "resource": self.resource,
        }

        logger.info("Refreshing token via %s", self.token_url)
        resp = requests.post(
            self.token_url,
            data=data,
            auth=(self.client_id, self.client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=5,
        )
        if not resp.ok:
            logger.error(
                "Token refresh failed: %s %s\nBody: %s",
                resp.status_code,
                resp.reason,
                resp.text[:1000],
            )
            raise RuntimeError(f"Token refresh failed: {resp.status_code} {resp.reason}")

        body = resp.json()
        access_token = body.get("access_token")
        token_type = body.get("token_type", "Bearer")
        expires_in = body.get("expires_in")

        if not access_token or not expires_in:
            raise RuntimeError(f"Invalid refresh response: {body}")

        self._tokens["access_token"] = access_token
        self._tokens["token_type"] = token_type
        self._tokens["expires_at"] = time.time() + int(expires_in) - 30  # 30초 여유
        self._save_tokens()
        return access_token

    def _ensure_token(self) -> str:
        # 1) 저장된 토큰이 있고 만료되지 않았다면 그대로 사용
        access_token = self._tokens.get("access_token")
        token_type = self._tokens.get("token_type", "Bearer")
        if access_token and not self._is_expired():
            return access_token

        # 2) refresh_token이 있으면 갱신
        if self._tokens.get("refresh_token"):
            return self._refresh_token()

        # 3) authorization_code 플로우로 토큰을 먼저 받아와야 함
        raise RuntimeError(
            "No valid access token. Please complete authorization_code flow and store tokens in "
            f"{self.tokens_file} (access_token, refresh_token, expires_at)."
        )

    # 간단한 Initialize 헬퍼 (MCP Gateway 샘플 요청)
    def initialize(
        self,
        protocol_version: str = "2025-06-18",
        client_name: str = "mcp-client",
        client_version: str = "0.1.0",
    ) -> Dict[str, Any]:
        params = {
            "protocolVersion": protocol_version,
            "capabilities": {"sampling": {}, "elicitation": {}, "roots": {"listChanged": True}},
            "clientInfo": {"name": client_name, "version": client_version},
        }
        result = self.call("initialize", params, skip_init=True)

        # initialize 응답에서 에러가 있으면 초기화 완료로 간주하지 않는다.
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(f"Initialize failed: {result}")

        self._initialized = True
        logger.info("MCP initialize success. session_id=%s", self.session_id)
        return result

    def call(self, method: str, params: Dict[str, Any], skip_init: bool = False) -> Dict[str, Any]:
        # initialize가 필요한 메서드라면 먼저 수행
        if not skip_init and method != "initialize" and not self._initialized:
            self.initialize()

        token = self._ensure_token()
        token_type = self._tokens.get("token_type", "Bearer")
        headers = {
            "Authorization": f"{token_type} {token}",
            "Content-Type": "application/json",
            # Initialize 단계에서 text/event-stream도 허용하도록 Accept 확장
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        }
        # 초기 initialize 전에 세션 헤더를 보내지 않음. 이후부터만 포함.
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        payload = {
            "jsonrpc": "2.0",
            "id": next(self._req_id),
            "method": method,
            "params": params,
        }
        url = self.base_url
        resp = requests.post(url, json=payload, headers=headers, timeout=10)

        # 응답 헤더에 세션 ID가 오면 저장 (대소문자 변형 대응)
        session_header = (
            resp.headers.get("Mcp-Session-Id")
            or resp.headers.get("mcp-session-id")
            or resp.headers.get("MCP-SESSION-ID")
        )
        if session_header:
            self.session_id = session_header
        else:
            # 응답 body에도 sessionId가 실려 있을 수 있으니 확인
            try:
                resp_json = resp.json()
                result_obj = resp_json.get("result") if isinstance(resp_json, dict) else None
                session_id_body = None
                if isinstance(result_obj, dict):
                    session_id_body = result_obj.get("sessionId") or result_obj.get("session_id")
                if session_id_body:
                    self.session_id = session_id_body
            except Exception:
                pass
        if not resp.ok:
            body_preview = resp.text[:2000]
            raise RuntimeError(f"MCP call failed {resp.status_code} {resp.reason}. Body: {body_preview}")
        content_type = resp.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            logger.error(
                "MCP response is not JSON. Content-Type=%s, Body=%s",
                content_type,
                resp.text[:1000],
            )
            raise RuntimeError("MCP response is not JSON")
        return resp.json()
