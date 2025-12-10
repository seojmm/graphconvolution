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
                "place_name": "육미안",
                "address": "서울특별시 강남구 역삼동 강남대로 100길 13",
                "estimated_price_per_person": 18000,
            },
            
            {
                "place_id": "place_456",
                "place_name": "센야 본점",
                "address": "서울특별시 강남구 역삼1동 753-1",
                "estimated_price_per_person": 23000,
                "allergens": ["견과류"],
            },
            
        ]

    def search_candidates(self, constraints: Constraints) -> List[MeetingCandidate]:
        # 아주 단순한 더미 필터: 예산/지역을 대충 보는 정도
        results: List[MeetingCandidate] = []

        max_budget = constraints.budget_per_person.max
        raw_areas = constraints.area or []
        # area가 dict(lat/lon)일 수 있으므로 문자열로 정규화
        areas: List[str] = []
        for a in raw_areas:
            if isinstance(a, str):
                areas.append(a)
            elif isinstance(a, dict):
                lat = a.get("lat")
                lon = a.get("lon")
                if lat and lon:
                    areas.append(f"{lat},{lon}")
        avoid_allergens = self._extract_allergy_keywords(constraints.hard_constraints)
        for idx, p in enumerate(self._places):
            if max_budget is not None and p["estimated_price_per_person"] > max_budget:
                continue
            if areas and not any(area in p["place_name"] or area in p["address"] for area in areas):
                continue
            
            place_allergens = set(p.get("allergens", []))  # 예: ["견과류"]
            if avoid_allergens and (place_allergens & avoid_allergens):
                # 예: avoid_allergens = {"견과류"}, place_allergens = {"견과류"} -> 후보 제외
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

    def _extract_allergy_keywords(self, hard_constraints: List[str]) -> set[str]:
        """
        hard_constraints에서 알레르기 관련 키워드를 추출.

        지원 포맷:
        - "allergy=견과류"
        - "견과류 알레르기" 같은 자연어
        """
        allergens: set[str] = set()

        for hc in hard_constraints or []:
            if not hc:
                continue
            text = hc.strip()

            # 1) canonical 포맷: "allergy=견과류"
            if text.startswith("allergy="):
                allergen = text.split("=", 1)[1].strip()
                if allergen:
                    allergens.add(allergen)
                continue

            # 2) 자연어 포맷: "견과류 알레르기"
            if "알레르기" in text:
                # "견과류 알레르기" -> "견과류"
                name = text.replace("알레르기", "").strip()
                if name:
                    allergens.add(name)

        return allergens
    

class Neo4jMeetingRepository(MeetingRepository):
    """
    GraphRAG/Neo4j 기반 구현을 위한 자리.

    - __init__에서 Neo4j 드라이버/세션을 초기화
    - search_candidates에서 Constraints를 바탕으로 GraphRAG 쿼리 실행 후 MeetingCandidate 리스트로 변환
    """

    def __init__(self, uri: str, user: str, password: str):
        self.uri = uri
        self.user = user
        self.password = password
        # TODO: neo4j 드라이버 초기화 코드 추가

    def search_candidates(self, constraints: Constraints) -> List[MeetingCandidate]:
        # TODO: GraphRAG/Neo4j 쿼리 구현
        return []
