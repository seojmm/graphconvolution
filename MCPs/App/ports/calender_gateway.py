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
    """톡캘린더 MCP 도구를 감싸는 어댑터.

    - 내부적으로는 PlayMCP에서 제공하는 TalkCalender 도구를 호출
    - ActionAgent는 MCP 세부사항을 몰라도 되고, 이 클래스만 사용
    """

    def __init__(self, talk_calender_client):
        """
        talk_calender_client: PlayMCP에서 제공하는 톡캘린더 MCP 클라이언트
          (예: talk_calender_client.call("CreateEvent", payload) 형태)
        """
        self.client = talk_calender_client

    def create_event(
        self,
        user_request: UserRequest,
        candidate: MeetingCandidate,
        attendees: Optional[List[str]] = None,
    ) -> ScheduleResult:
        payload = {
            "title": f"[약속] {candidate.place_name}",
            "start_time": candidate.start_time,
            "end_time": candidate.end_time,
            "location": candidate.address,
            "attendees": attendees or [p.participant_id for p in user_request.participants],
            "description": user_request.user_query,
        }

        # 실제 MCP 호출 (구체적인 호출 방식은 PlayMCP SDK 스펙에 맞게 수정)
        result = self.client.call("CreateEvent", payload)

        return ScheduleResult(
            status="created",
            event_id=result["event_id"],
            candidate_id=candidate.id,
        )
