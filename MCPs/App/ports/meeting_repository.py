#나중에 DB 팀이 할 일:
#Neo4jMeetingRepository(MeetingRepository) 같은 구현체를 추가해서
#search_candidates() 안에서 Text-to-Cypher/GraphRAG 파이프라인을 구현하면 됨.

from abc import ABC, abstractmethod
from typing import List

from ..Domain.model import Constraints, MeetingCandidate


class MeetingRepository(ABC):
    """Meeting-related 데이터(장소, 타임슬롯 등)를 조회하는 포트.

    DB 팀은 이 인터페이스를 구현해서 Neo4j / RDB / Search 인프라를 붙이게 됩니다.
    Orchestrator와 KnowledgeAgent는 이 인터페이스만 의존합니다.
    """

    @abstractmethod
    def search_candidates(self, constraints: Constraints) -> List[MeetingCandidate]:
        """Return a list of candidate meetings that satisfy given constraints.

        이 메서드 안에서 그래프 쿼리, 벡터 검색, 필터링을 조합해서 구현하면 됩니다.
        """
        raise NotImplementedError


# 선택: DB 없이도 테스트하고 싶다면 InMemory 구현 예시를 둘 수 있습니다.
class InMemoryMeetingRepository(MeetingRepository):
    def __init__(self):
        self._places = [
            {
                "place_id": "place_123",
                "place_name": "강남OO고기집",
                "address": "서울 강남구 강남대로 123",
                "estimated_price_per_person": 18000,
            },
            {
                "place_id": "place_456",
                "place_name": "역삼AA이자카야",
                "address": "서울 강남구 테헤란로 456",
                "estimated_price_per_person": 23000,
            },
        ]

    def search_candidates(self, constraints: Constraints) -> List[MeetingCandidate]:
        # 아주 단순한 더미 필터: 예산/지역을 대충 보는 정도
        results: List[MeetingCandidate] = []

        max_budget = constraints.budget_per_person.max
        areas = constraints.area or []

        for idx, p in enumerate(self._places):
            if max_budget is not None and p["estimated_price_per_person"] > max_budget:
                continue
            if areas and not any(area in p["place_name"] or area in p["address"] for area in areas):
                continue

            # 날짜/시간은 여기서는 간단히 constraints에서 그대로 가져옴
            start_date = constraints.date_range.start_date or "2025-11-28"
            start_time = constraints.time_range.start_time or "19:00"
            end_time = constraints.time_range.end_time or "21:00"

            candidate = MeetingCandidate(
                id=f"c_{idx}",
                request_id="req_dummy",
                place_name=p["place_name"],
                place_id=p["place_id"],
                address=p["address"],
                start_time=f"{start_date}T{start_time}:00+09:00",
                end_time=f"{start_date}T{end_time}:00+09:00",
                estimated_price_per_person=p["estimated_price_per_person"],
                reasoning="InMemoryMeetingRepository dummy candidate",
            )
            results.append(candidate)

        return results
