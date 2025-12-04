# MCPs/kakao_auth.py

import os
import json
import urllib.parse

import requests
from dotenv import load_dotenv
from fastapi import APIRouter  # ✅ FastAPI에서 가져오는 거
from fastapi.responses import RedirectResponse, HTMLResponse
import requests

load_dotenv()

router = APIRouter()

CLIENT_ID = os.environ["KAKAO_CLIENT_ID"]
CLIENT_SECRET = os.environ["KAKAO_CLIENT_SECRET"]
REDIRECT_URI = os.environ["KAKAO_REDIRECT_URI"]

AUTH_URL = os.getenv("KAKAO_AUTH_URL", "https://kauth.kakao.com/oauth/authorize")
TOKEN_URL = os.getenv("KAKAO_TOKEN_URL", "https://kauth.kakao.com/oauth/token")

# 토큰을 간단히 파일 하나에 저장 (나중에 DB로 빼고 싶으면 이 부분만 교체)
TOKENS_FILE = ".kakao_oauth_tokens.json"


@router.get("/kakao/login")
def kakao_login():
    """
    브라우저로 접속해서 카카오 로그인을 진행시키는 엔드포인트.
    http://localhost:8000/auth/kakao/login 열면 카카오 로그인 화면으로 리다이렉트됨.
    """
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        # 콘솔에서 설정한 scope에 맞게 수정 (톡캘린더 권한 포함)
        "scope": "talk_calendar",
    }
    url = AUTH_URL + "?" + urllib.parse.urlencode(params)
    return RedirectResponse(url)


@router.get("/kakao/callback")
def kakao_callback(code: str):
    """
    카카오에서 보내주는 code를 가지고 access_token/refresh_token을 발급받는 부분.
    """
    data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }

    res = requests.post(TOKEN_URL, data=data)
    res.raise_for_status()
    tokens = res.json()

    # { "access_token": "...", "refresh_token": "...", ... } 이런 형태로 저장됨
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(tokens, f, ensure_ascii=False, indent=2)

    return HTMLResponse(
        "<h1>카카오 로그인 완료</h1>"
        "<p>.kakao_oauth_tokens.json 에 토큰 저장됨. 이제 브라우저 닫고 API 호출해도 돼요.</p>"
    )


def load_access_token() -> str:
    """
    다른 모듈(예: 캘린더 게이트웨이)에서 쓰기 위한 helper.
    파일에서 access_token만 꺼내온다.
    """
    if not os.path.exists(TOKENS_FILE):
        raise RuntimeError(
            "아직 카카오 토큰이 없습니다. 먼저 /auth/kakao/login 으로 들어가서 로그인부터 해주세요."
        )

    with open(TOKENS_FILE, encoding="utf-8") as f:
        tokens = json.load(f)
    return tokens["access_token"]
