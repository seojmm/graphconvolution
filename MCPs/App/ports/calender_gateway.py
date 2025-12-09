import json
import re
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any

from ..Domain.model import ScheduleResult, MeetingCandidate, UserRequest
from datetime import datetime

from datetime import datetime

class CalenderGateway(ABC):
    """
    캘린더/알림 시스템 포트 (예: 톡캘린더).
    톡캘린더 API를 호출해서 일정 생성 → 생성된 event_id / 링크를 돌려주는 어댑터 역할
    """

    @abstractmethod
    def create_event(
        self,
        user_request: UserRequest,
        candidate: MeetingCandidate,
        attendees: Optional[List[str]] = None,
    ) -> ScheduleResult:
        """Create a calender event and return an identifier."""
        raise NotImplementedError


class DummyCalenderGateway(CalenderGateway):
    """DB 없이 테스트용으로 쓸 수 있는 in-memory/mock 구현."""

    def create_event(
        self,
        user_request: UserRequest,
        candidate: MeetingCandidate,
        attendees: Optional[List[str]] = None,
    ) -> ScheduleResult:
        # 간단히 문자열 기반 event_id 생성
        event_id = f"evt_{candidate.candidate_id}"
        return ScheduleResult(
            status="mocked",
            event_id=event_id,
            candidate_id=candidate.candidate_id,
        )


# *** 여기부터가 실제 톡캘린더 MCP 연동용 ***
class KakaoCalenderGateway(CalenderGateway):
    """
    톡캘린더 MCP 클라이언트를 감싸는 어댑터.

    - talk_calender_client는 PlayMCP SDK 등에서 제공하는 MCP 클라이언트 인스턴스여야 함.
    - `call(action, payload)` 형태로 호출한다고 가정.
    """

    def __init__(self, talk_calender_client, default_calendar_id: str = "primary"):
        self.client = talk_calender_client
        self.default_calendar_id = default_calendar_id

    def create_event(
        self,
        user_request: UserRequest,
        candidate: MeetingCandidate,
        attendees: Optional[List[str]] = None,
    ) -> ScheduleResult:
        # "음력" 언급 시 즉시 중단
        if "음력" in user_request.user_query:
            raise RuntimeError("음력 일정은 지원하지 않습니다.")

        # 시간 문자열을 로컬(타임존 오프셋 제거) ISO 8601 형식으로 맞춤
        def _normalize_time(value: str) -> str:
            try:
                dt = datetime.fromisoformat(value)
                return dt.replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")
            except Exception:
                return value

        # MCP 도구 스펙에 맞춰 최소 필드만 전달 (추론/기본값 금지)
        arguments = {
            "title": candidate.place_name,
            "time": {
                "startAt": _normalize_time(candidate.start_time),
                "endAt": _normalize_time(candidate.end_time),
            },
            "description": user_request.user_query,
            "location": {
                "name": candidate.place_name,
                "address": candidate.address,
            },
        }

        # MCP 도구 호출: MCP 표준 메서드인 tools/call 사용
        rpc_result = self.client.call(
            "tools/call",
            {
                "name": "KakaotalkCal-CreateEvent",  # tools/list로 확인된 실제 도구 이름
                "arguments": arguments,
            },
        )

        # JSON-RPC result payload에서 이벤트 ID 추출
        result_obj = rpc_result.get("result") if isinstance(rpc_result, dict) else None

        # 서버가 isError 플래그로 실패를 알려주는 경우, 메시지를 그대로 노출
        if isinstance(result_obj, dict) and result_obj.get("isError"):
            content = result_obj.get("content")
            err_msg = None
            if isinstance(content, list) and content:
                first = content[0]
                if isinstance(first, dict) and first.get("type") == "text":
                    err_msg = first.get("text")
            raise RuntimeError(err_msg or f"CreateEvent 호출 실패: {rpc_result}")

        event_id = None
        if isinstance(result_obj, dict):
            event_id = (
                result_obj.get("event_id")
                or result_obj.get("eventId")
                or result_obj.get("id")
            )
            if not event_id:
                content = result_obj.get("content")
                if isinstance(content, list) and content:
                    first = content[0]
                    if isinstance(first, dict) and first.get("type") == "text":
                        event_id = first.get("text")
        # PlayMCP UI에서 확인한 형태처럼 content[].text 로 event_id가 오는 경우 처리
        if not event_id and isinstance(rpc_result, dict):
            content = rpc_result.get("content")
            if isinstance(content, list) and content:
                first = content[0]
                if isinstance(first, dict) and first.get("type") == "text":
                    event_id = first.get("text")
        if not event_id:
            raise RuntimeError(f"CreateEvent 응답에 event_id가 없습니다: {rpc_result}")
        

        route_lines: List[str] = []  # [추가]

        for p in (user_request.participants or []):  # [추가]
            origin = getattr(p, "home_anchor", None)
            if not origin:
                continue

            map_arguments = {
                "origin": origin,
                "destination": candidate.place_name,
            }

            try:
                map_rpc = self.client.call(
                    "tools/call",
                    {
                        "name": "KakaoMap-GetPublicTransitDirections",
                        "arguments": map_arguments,
                    },
                )
                # print("[MemoChat][ETA] raw resp:", json.dumps(map_rpc, indent=2, ensure_ascii=False))
            except Exception as e:
                print("[MemoChat][ETA] KakaoMap MCP 호출 실패:", repr(e))
                continue

            result = map_rpc.get("result") if isinstance(map_rpc, dict) else None
            content = result.get("content") if isinstance(result, dict) else None
            if not isinstance(content, list) or not content:
                continue

            first = content[0]
            if not isinstance(first, dict) or first.get("type") != "text":
                continue

            text = first.get("text", "")
            if not isinstance(text, str):
                continue

            # "총 거리: 15.3km" 파싱 [추가]
            distance_km = None
            m_dist = re.search(r"총 거리\s*:\s*([0-9\.]+)\s*km", text)
            if m_dist:
                try:
                    distance_km = float(m_dist.group(1))
                except ValueError:
                    distance_km = None

            # "소요시간: 40분" 파싱 [추가]
            duration_min = None
            m_dur = re.search(r"소요시간\s*:\s*([0-9]+)\s*분", text)
            if m_dur:
                try:
                    duration_min = float(m_dur.group(1))
                except ValueError:
                    duration_min = None

            # "[카카오맵](https://...)" 링크 파싱 [추가]
            map_url = None
            m_url = re.search(r"\((https?://[^\)]+)\)", text)
            if m_url:
                map_url = m_url.group(1)

            if distance_km is None and duration_min is None and map_url is None:
                continue

            label = p.name or origin
            parts = []
            if distance_km is not None:
                parts.append(f"총 거리 {distance_km}km")
            if duration_min is not None:
                parts.append(f"소요시간 {int(duration_min)}분")
            if map_url:
                parts.append(f"경로 {map_url}")

            route_lines.append(f"- {label}: " + ", ".join(parts))

        return ScheduleResult(
            status="created",
            event_id=event_id,
            candidate_id=candidate.id,
        )


class KakaoMemoChatGateway:
    """톡 나에게 보내기(MemoChat) MCP 호출용."""

    def __init__(self, client):
        self.client = client

    def send_message(self, message: str) -> Dict[str, Any]:
        return self.client.call(
            "tools/call",
            {
                "name": "KakaotalkChat-MemoChat",
                "arguments": {
                    "message": message,
                },
            },
        )


class KakaoMapGateway:
    """카카오맵 MCP 호출용 (대중교통 경로)."""

    def __init__(self, client):
        self.client = client

    def get_transit_directions(self, origin: str, destination: str) -> Dict[str, Any]:
        return self.client.call(
            "tools/call",
            {
                "name": "KakaoMap-GetPublicTransitDirections",
                "arguments": {
                    "origin": origin,
                    "destination": destination,
                },
            },
        )

    def search_place(self, keyword: str, highlighted_region: Optional[str] = None) -> Dict[str, Any]:
        args = {"keyword": keyword}
        if highlighted_region:
            args["highlightedRegion"] = highlighted_region
        return self.client.call(
            "tools/call",
            {
                "name": "KakaoMap-SearchPlaceByKeywordOpen",
                "arguments": args,
            },
        )
