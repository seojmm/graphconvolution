from typing import List
from typing_extensions import NotRequired, TypedDict

from langgraph.graph import StateGraph, END

from ..Domain.model import (
    UserRequest,
    OrchestratorResult,
    MeetingCandidate,
    Constraints,
)
from ..agents.constraint_extraction import ConstraintExtractionAgent
from ..agents.knowledge_agent import KnowledgeAgent
from ..agents.verification_agent import VerificationAgent
from ..ports.midpoint_service import MidpointService


class PlannerState(TypedDict):
    """LangGraph 상태 스키마. 키별 채널을 분리해 __root__ 충돌을 방지."""

    user_request: UserRequest
    constraints: NotRequired[Constraints]
    candidates: NotRequired[List[MeetingCandidate]]
    participants: NotRequired[List]


class PlanningAgent:
    """제약 추출 → (중간지점 보정) → 후보 생성 → 검증까지 담당하는 플래닝 에이전트."""

    def __init__(
        self,
        constraint_agent: ConstraintExtractionAgent,
        knowledge_agent: KnowledgeAgent,
        verification_agent: VerificationAgent,
        midpoint_service: MidpointService | None = None,
    ):
        self.constraint_agent = constraint_agent
        self.knowledge_agent = knowledge_agent
        self.verification_agent = verification_agent
        self.midpoint_service = midpoint_service
        self.plan_builder, self.plan_graph = self._build_plan_graph()

    def plan(self, user_request: UserRequest) -> OrchestratorResult:
        """LangGraph 기반 플로우로 후보 미팅 카드 생성."""
        state = self.plan_graph.invoke({"user_request": user_request})
        constraints = state.get("constraints")
        candidates = state.get("candidates", [])
        participants = state.get("participants", user_request.participants)

        # final_score 기준 Top-3만 노출
        ranked = sorted(candidates, key=lambda c: (c.final_score or 0.0), reverse=True)
        top_candidates = ranked[:3]

        return OrchestratorResult(
            constraints=constraints,
            candidates=top_candidates,
            participants=participants,
        )

    def _build_plan_graph(self):
        graph = StateGraph(PlannerState)

        def node_extract(state):
            user_request: UserRequest = state["user_request"]
            constraints = self.constraint_agent.extract(user_request)
            return {"constraints": constraints, "participants": user_request.participants}

        def node_midpoint(state):
            constraints: Constraints = state["constraints"]
            if (
                constraints.meeting_point_strategy == "midpoint"
                and self.midpoint_service
                and constraints.departure_points
            ):
                areas = self.midpoint_service.suggest_meeting_areas(constraints.departure_points)
                if areas:
                    constraints.area = areas
            return {"constraints": constraints}

        def node_propose(state):
            constraints: Constraints = state["constraints"]
            candidates = self.knowledge_agent.propose_candidates(constraints)
            return {"constraints": constraints, "candidates": candidates}

        def node_verify(state):
            constraints: Constraints = state.get("constraints")
            if constraints is None:
                return {}
            participants = state.get("participants", [])
            candidates = state.get("candidates", [])
            evaluated = self.verification_agent.evaluate(
                constraints=constraints,
                candidates=candidates,
                participants=participants,
            )
            return {"constraints": constraints, "candidates": evaluated}

        graph.add_node("extract", node_extract)
        graph.add_node("midpoint", node_midpoint)
        graph.add_node("propose", node_propose)
        graph.add_node("verify", node_verify)

        def needs_midpoint(state):
            constraints: Constraints = state["constraints"]
            return (
                constraints.meeting_point_strategy == "midpoint"
                and self.midpoint_service is not None
                and bool(constraints.departure_points)
            )

        graph.add_conditional_edges(
            "extract",
            needs_midpoint,
            {True: "midpoint", False: "propose"},
        )
        graph.add_edge("midpoint", "propose")
        graph.add_edge("propose", "verify")
        graph.add_edge("verify", END)
        graph.set_entry_point("extract")

        return graph, graph.compile()
