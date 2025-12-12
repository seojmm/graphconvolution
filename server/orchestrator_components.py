"""Lightweight orchestrator components merged from MCPs.

This keeps the same high-level agents (constraint, knowledge, verification, action)
but with cleaner, deterministic logic suitable for the unified FastAPI server.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import List, Optional

from models import (
    Constraints,
    UserRequest,
    MeetingCandidate,
    ScheduleResult,
    OrchestratorResult,
    EtaStats,
    BudgetPerPerson,
    DateRange,
    TimeRange,
)


# ------------------------------
# Ports / simple services
# ------------------------------


class InMemoryMeetingRepository:
    """Very small in-memory repository used for demo/testing."""

    def __init__(self) -> None:
        self._places = [
            {
                "place_id": "place_123",
                "place_name": "강남 고기집",
                "address": "서울 강남구 테헤란로 123",
                "estimated_price_per_person": 18000,
            },
            {
                "place_id": "place_456",
                "place_name": "연남동 파스타",
                "address": "서울 마포구 동교로 22",
                "estimated_price_per_person": 23000,
            },
            {
                "place_id": "place_789",
                "place_name": "을지로 포장마차",
                "address": "서울 중구 을지로 12",
                "estimated_price_per_person": 12000,
            },
        ]

    def search_candidates(self, constraints: Constraints) -> List[MeetingCandidate]:
        results: List[MeetingCandidate] = []
        max_budget = constraints.budget_per_person.max
        areas = constraints.area or []

        for idx, p in enumerate(self._places):
            if max_budget is not None and p["estimated_price_per_person"] > max_budget:
                continue
            if areas and not any(area in p["place_name"] or area in p["address"] for area in areas):
                continue

            start_date = constraints.date_range.start_date or "2025-12-05"
            start_time = constraints.time_range.start_time or "19:00"
            end_time = constraints.time_range.end_time or "21:00"

            candidate = MeetingCandidate(
                id=f"c_{idx}",
                request_id=str(uuid.uuid4()),
                place_name=p["place_name"],
                place_id=p["place_id"],
                address=p["address"],
                start_time=f"{start_date}T{start_time}:00+09:00",
                end_time=f"{start_date}T{end_time}:00+09:00",
                estimated_price_per_person=p["estimated_price_per_person"],
                reasoning="In-memory candidate",
            )
            results.append(candidate)

        return results


@dataclass
class EtaService:
    """Dummy ETA service that returns simple stats based on participant count."""

    base_minutes: int = 20

    def get_eta_stats(self, participants_count: int) -> EtaStats:
        avg = self.base_minutes + participants_count * 2
        return EtaStats(avg=avg, max=avg + 10, std=5.0)


@dataclass
class CalenderGateway:
    """Stub calendar gateway that pretends to create an event."""

    provider: str = "kanana-demo"

    def create_event(self, user_request: UserRequest, candidate: MeetingCandidate) -> ScheduleResult:
        return ScheduleResult(
            status="scheduled",
            event_id=str(uuid.uuid4()),
            candidate_id=candidate.id,
        )


# ------------------------------
# Agents
# ------------------------------


class ConstraintExtractionAgent:
    """Parse simple constraints from the user query (mock logic)."""

    def extract(self, user_request: UserRequest) -> Constraints:
        text = user_request.user_query

        people_count: Optional[int] = None
        budget_max: Optional[int] = None
        areas: List[str] = []
        categories: List[str] = []

        # crude parsing
        for token in text.split():
            if token.endswith("명") and token[:-1].isdigit():
                people_count = int(token[:-1])
            if token.endswith("만원") and token[:-2].isdigit():
                budget_max = int(token[:-2]) * 10000

        for kw in ["강남", "홍대", "마포", "을지로", "용산", "서초"]:
            if kw in text:
                areas.append(kw)

        for kw in ["고기", "파스타", "카페", "회", "포차"]:
            if kw in text:
                categories.append(kw)

        return Constraints(
            people_count=people_count,
            area=areas,
            date_range=DateRange(type="single_day"),
            time_range=TimeRange(),
            budget_per_person=BudgetPerPerson(max=budget_max, currency="KRW"),
            category_preferences=categories,
            hard_constraints=[],
            soft_constraints=[],
            raw_normalized_text=text,
        )


class KnowledgeAgent:
    def __init__(self, meeting_repository: InMemoryMeetingRepository):
        self.meeting_repository = meeting_repository

    def propose_candidates(self, constraints: Constraints) -> List[MeetingCandidate]:
        return self.meeting_repository.search_candidates(constraints)


class VerificationAgent:
    def __init__(self, eta_service: EtaService):
        self.eta_service = eta_service

    def evaluate(
        self,
        constraints: Constraints,
        candidates: List[MeetingCandidate],
        participants: List,
    ) -> List[MeetingCandidate]:
        count = len(participants)
        eta_stats = self.eta_service.get_eta_stats(count)

        scored: List[MeetingCandidate] = []
        for cand in candidates:
            # simple scoring: budget fit + category pref length
            budget_score = 1.0
            max_budget = constraints.budget_per_person.max
            if max_budget and cand.estimated_price_per_person:
                budget_score = 1.0 if cand.estimated_price_per_person <= max_budget else 0.2

            pref_score = 1.0 if not constraints.category_preferences else 0.5
            cand.metrics = cand.metrics or None
            cand.eta_stats = eta_stats
            cand.satisfaction_score = round((budget_score + pref_score) / 2, 2)
            scored.append(cand)

        scored.sort(key=lambda c: c.satisfaction_score or 0, reverse=True)
        return scored


class ActionAgent:
    def __init__(self, calender_gateway: CalenderGateway):
        self.calender_gateway = calender_gateway

    def schedule_meeting(self, user_request: UserRequest, selected_candidate: MeetingCandidate) -> ScheduleResult:
        return self.calender_gateway.create_event(user_request, selected_candidate)


class Orchestrator:
    def __init__(
        self,
        constraint_agent: ConstraintExtractionAgent,
        knowledge_agent: KnowledgeAgent,
        verification_agent: VerificationAgent,
        action_agent: ActionAgent,
    ) -> None:
        self.constraint_agent = constraint_agent
        self.knowledge_agent = knowledge_agent
        self.verification_agent = verification_agent
        self.action_agent = action_agent

    def plan(self, user_request: UserRequest) -> OrchestratorResult:
        constraints = self.constraint_agent.extract(user_request)
        candidates = self.knowledge_agent.propose_candidates(constraints)
        evaluated = self.verification_agent.evaluate(constraints, candidates, user_request.participants)
        return OrchestratorResult(constraints=constraints, candidates=evaluated)

    def schedule(self, user_request: UserRequest, selected_candidate: MeetingCandidate) -> ScheduleResult:
        return self.action_agent.schedule_meeting(user_request, selected_candidate)


def build_orchestrator() -> Orchestrator:
    repo = InMemoryMeetingRepository()
    constraint_agent = ConstraintExtractionAgent()
    knowledge_agent = KnowledgeAgent(repo)
    verification_agent = VerificationAgent(EtaService())
    action_agent = ActionAgent(CalenderGateway())
    return Orchestrator(
        constraint_agent=constraint_agent,
        knowledge_agent=knowledge_agent,
        verification_agent=verification_agent,
        action_agent=action_agent,
    )
