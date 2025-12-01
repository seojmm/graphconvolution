from typing import List

from ..Domain.model import Constraints, MeetingCandidate
from ..ports.meeting_repository import MeetingRepository


#Knowledge Agent (Hybrid Search & Reasoner)
#Neo4j 구현 예정 - Graph + Vector + KakaoMap 장소 검색 / GraphRAG 기반 hyperedge(=MeetingCandidate) 생성

class KnowledgeAgent:
    """Graph + Vector + Rules 를 이용해 후보 미팅을 생성하는 에이전트.

    - 직접 DB를 보지 않고, MeetingRepository 포트만 의존.
    - DB 팀은 MeetingRepository 구현체(예: Neo4jMeetingRepository)를 만들어 주입하면 됨.
    """

    def __init__(self, meeting_repository: MeetingRepository):
        self.meeting_repository = meeting_repository

    def propose_candidates(self, constraints: Constraints) -> List[MeetingCandidate]:
        """주어진 제약 조건을 만족하는 후보 리스트를 반환."""
        candidates = self.meeting_repository.search_candidates(constraints)

        # TODO: 후보 수가 너무 적을 경우 제약 완화/재탐색 로직 추가
        # 예: 예산 상향, 지역 반경 확장, 시간대 확장 등
        return candidates
