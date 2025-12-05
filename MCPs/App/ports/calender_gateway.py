from abc import ABC, abstractmethod
from typing import List, Optional

from ..Domain.model import ScheduleResult, MeetingCandidate, UserRequest

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

        return ScheduleResult(
            status="created",
            event_id=event_id,
            candidate_id=candidate.id,
        )
