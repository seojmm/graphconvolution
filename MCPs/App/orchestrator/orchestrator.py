from ..Domain.model import UserRequest, OrchestratorResult, ScheduleResult, MeetingCandidate
from ..agents.constraint_extraction import ConstraintExtractionAgent
from ..agents.knowledge_agent import KnowledgeAgent
from ..agents.verification_agent import VerificationAgent
from ..agents.action_agent import ActionAgent

#AI Agent Orchestrator (Planner)
class Orchestrator:
    """모든 에이전트를 조합해 end-to-end 플로우를 관리하는 두뇌.

    1) ConstraintExtractionAgent로 자연어 -> Constraints
    2) KnowledgeAgent로 후보 리스트 생성
    3) VerificationAgent로 형평성/품질 평가
    4) (선택) ActionAgent로 최종 후보를 실제 일정으로 확정
    """

    def __init__(
        self,
        constraint_agent: ConstraintExtractionAgent,
        knowledge_agent: KnowledgeAgent,
        verification_agent: VerificationAgent,
        action_agent: ActionAgent,
    ):
        self.constraint_agent = constraint_agent
        self.knowledge_agent = knowledge_agent
        self.verification_agent = verification_agent
        self.action_agent = action_agent

    def plan(self, user_request: UserRequest) -> OrchestratorResult:
        """후보 미팅 카드까지 생성하는 단계 (캘린더 생성 전)."""
        # 1) 자연어 -> 제약 추출
        constraints = self.constraint_agent.extract(user_request)

        # 2) KnowledgeAgent로 후보 생성 (DB/그래프 사용)
        raw_candidates = self.knowledge_agent.propose_candidates(constraints)

        # 3) VerificationAgent로 형평성/품질 평가
        evaluated_candidates = self.verification_agent.evaluate(
            constraints=constraints,
            candidates=raw_candidates,
            participants=user_request.participants,
        )

        return OrchestratorResult(
            constraints=constraints,
            candidates=evaluated_candidates,
        )

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
