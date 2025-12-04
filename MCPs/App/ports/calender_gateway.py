from abc import ABC, abstractmethod
from typing import List, Optional

from ..Domain.model import ScheduleResult, MeetingCandidate, UserRequest

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
        calendar_id = getattr(user_request, "calendar_id", None) or self.default_calendar_id
        payload = {
            "calendar_id": calendar_id,
            "title": candidate.place_name,
            "start_at": candidate.start_time,
            "end_at": candidate.end_time,
            "time_zone": "Asia/Seoul",
            "all_day": False,
            "location": {
                "name": candidate.place_name,
                "address": candidate.address,
            },
            "description": user_request.user_query,
            "attendees": attendees or [p.participant_id for p in user_request.participants],
        }

        # MCP 액션 이름은 실제 톡캘린더 MCP 스펙에 맞게 수정 필요 (예: "CreateEvent")
        result = self.client.call("CreateEvent", payload)

        return ScheduleResult(
            status="created",
            event_id=result.get("event_id") or result.get("id"),
            candidate_id=candidate.id,
        )
