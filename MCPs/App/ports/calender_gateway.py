from abc import ABC, abstractmethod
from typing import List, Optional
from ..Domain.model import ScheduleResult, MeetingCandidate, UserRequest
import requests  # <= 새로 추가
from MCPs.kakao_auth import load_access_token  # <= 새로 추가
import json

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
    톡캘린더 REST API를 직접 호출하는 구현체.

    - 내부적으로는 POST https://kapi.kakao.com/v2/api/calendar/create/event 를 사용
    - ActionAgent / Orchestrator 입장에서는 그냥 "일정 만들어주는 함수"로 쓰면 됨

    """

    def __init__(self, default_calendar_id: str = "primary"):
        # 기본적으로는 유저의 기본 캘린더(primary)에 생성
        self.default_calendar_id = default_calendar_id

    def create_event(
        self,
        user_request: UserRequest,
        candidate: MeetingCandidate,
        attendees: Optional[List[str]] = None,
    ) -> ScheduleResult:
        # 1) OAuth에서 발급받은 access_token 읽기
        access_token = load_access_token()

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        }

        # TODO: UserRequest에 별도의 calendar_id 필드를 나중에 추가하고 싶으면 여기서 우선순위로 사용
        calendar_id = getattr(user_request, "calendar_id", None) or self.default_calendar_id

        # 2) 톡캘린더 REST API 스펙에 맞게 event body 구성
        #    공식 문서: POST /v2/api/calendar/create/event, body: calendar_id + event(JSON):contentReference[oaicite:4]{index=4}
        event_body = {
            "title": candidate.place_name,  # 일정 제목
            "time": {
                "start_at": candidate.start_time,  # 현재는 ISO 문자열 그대로 사용 (필요하면 UTC 변환)
                "end_at": candidate.end_time,
                "time_zone": "Asia/Seoul",
                "all_day": False,
                "lunar": False,
            },
            "location": {
                "name": candidate.place_name,
                "address": candidate.address,
            },
            "description": user_request.user_query,
            # reminders, color 등 추가 옵션이 필요하면 여기서 더 채워 넣으면 됨
        }

        data = {
            "calendar_id": calendar_id,
            "event": json.dumps(event_body, ensure_ascii=False),
        }

        # 3) 카카오 톡캘린더 "일반 일정 생성" API 호출
        resp = requests.post(
            "https://kapi.kakao.com/v2/api/calendar/create/event",
            headers=headers,
            data=data,
            timeout=5,
        )
        resp.raise_for_status()
        body = resp.json()

        # 응답은 { "event_id": "..." } 형태:contentReference[oaicite:5]{index=5}
        event_id = body["event_id"]

        return ScheduleResult(
            status="created",
            event_id=event_id,
            candidate_id=candidate.id,
        )