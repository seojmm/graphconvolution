from ..Domain.model import UserRequest, OrchestratorResult, ScheduleResult, MeetingCandidate
from ..agents.planning_agent import PlanningAgent
from ..agents.action_agent import ActionAgent


class Orchestrator:
    """플래닝(PlanningAgent)과 실행(ActionAgent)을 조합하는 오케스트레이터."""

    def __init__(
        self,
        planning_agent: PlanningAgent,
        action_agent: ActionAgent,
    ):
        self.planning_agent = planning_agent
        self.action_agent = action_agent
        # 호환성: plan_graph/plan_builder를 외부에서 사용할 수 있도록 연결
        self.plan_graph = getattr(planning_agent, "plan_graph", None)
        self.plan_builder = getattr(planning_agent, "plan_builder", None)

    def plan(self, user_request: UserRequest) -> OrchestratorResult:
        """후보 미팅 카드 생성(PlanningAgent 위임)."""
        return self.planning_agent.plan(user_request)

    def schedule(
        self,
        user_request: UserRequest,
        selected_candidate: MeetingCandidate,
    ) -> ScheduleResult:
        """사용자가 후보 중 하나를 선택했을 때, 실제 일정을 생성하는 단계."""
        return self.action_agent.schedule_meeting(
            user_request=user_request,
            selected_candidate=selected_candidate,
        )
