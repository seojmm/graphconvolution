from ..Domain.model import MeetingCandidate, UserRequest, ScheduleResult
from ..ports.calender_gateway import CalenderGateway


#Action Agent (Execution)
#톡캘린더 MCP 일정 생성(CreateEvent, 중복 확인(GetEvent))

# ToDo 나중에 필요하면 중복 일정 체크/권한 검사 등의 비즈니스 로직 추가
class ActionAgent:
    """선택된 후보를 실제 캘린더 이벤트로 만드는 에이전트."""

    def __init__(self,calender_gateway: CalenderGateway):
        self.calender_gateway = calender_gateway


    def schedule_meeting(self, user_request, selected_candidate):
        return self.calender_gateway.create_event(
            user_request=user_request,
            candidate=selected_candidate,
            attendees=[p.participant_id for p in user_request.participants],
        )
