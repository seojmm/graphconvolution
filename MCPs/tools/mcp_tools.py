"""
LangChain Tool wrappers for MCP Gateway actions.
- 톡캘린더 일정 생성
- 톡 나에게 보내기(MemoChat)
- 대중교통 길찾기
- 장소 검색

모든 Tool은 매 호출 시 .env의 PLAY_MCP_* 설정으로 PlayMCPClient를 생성합니다.
"""

import os
from typing import Optional, Dict, Any

from langchain_core.tools import tool

from MCPs.kakao_mcp import PlayMCPClient


def _client() -> PlayMCPClient:
    base_url = (
        os.getenv("PLAY_MCP_ENDPOINT")
        or os.getenv("PLAY_MCP_TOOLBOX_URL")
        or "https://playmcp.kakao.com/mcp"
    )
    return PlayMCPClient(base_url=base_url)


@tool
def mcp_create_event(title: str, start_at: str, end_at: str, name: Optional[str] = None, address: Optional[str] = None) -> Dict[str, Any]:
    """
    톡캘린더 일정 생성(KakaotalkCal-CreateEvent).
    Args:
        title: 일정 제목
        start_at: 시작 시각(ISO, local)
        end_at: 종료 시각(ISO, local)
        name: 장소 이름 (옵션)
        address: 주소 (옵션)
    """
    client = _client()
    payload = {
        "title": title,
        "time": {"startAt": start_at, "endAt": end_at},
    }
    loc = {}
    if name:
        loc["name"] = name
    if address:
        loc["address"] = address
    if loc:
        payload["location"] = loc
    return client.call("tools/call", {"name": "KakaotalkCal-CreateEvent", "arguments": payload})


@tool
def mcp_memo_chat(message: str) -> Dict[str, Any]:
    """
    톡 나에게 보내기(KakaotalkChat-MemoChat).
    Args:
        message: 전송할 텍스트
    """
    client = _client()
    return client.call(
        "tools/call",
        {"name": "KakaotalkChat-MemoChat", "arguments": {"message": message}},
    )


@tool
def mcp_transit_directions(origin: str, destination: str) -> Dict[str, Any]:
    """
    대중교통 길찾기(KakaoMap-GetPublicTransitDirections).
    Args:
        origin: 출발지
        destination: 도착지
    """
    client = _client()
    return client.call(
        "tools/call",
        {
            "name": "KakaoMap-GetPublicTransitDirections",
            "arguments": {"origin": origin, "destination": destination},
        },
    )


@tool
def mcp_search_place(keyword: str, highlighted_region: Optional[str] = None) -> Dict[str, Any]:
    """
    장소 검색(KakaoMap-SearchPlaceByKeywordOpen).
    Args:
        keyword: 검색어
        highlighted_region: 강조 지역 (옵션)
    """
    client = _client()
    args = {"keyword": keyword}
    if highlighted_region:
        args["highlightedRegion"] = highlighted_region
    return client.call(
        "tools/call",
        {"name": "KakaoMap-SearchPlaceByKeywordOpen", "arguments": args},
    )
