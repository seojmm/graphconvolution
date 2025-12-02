from abc import ABC, abstractmethod
from typing import List


class MidpointService(ABC):
    """출발지 리스트를 받아 만남 후보 지역(역/동 등)을 반환하는 포트."""

    @abstractmethod
    def suggest_meeting_areas(self, departure_points: List[str]) -> List[str]:
        raise NotImplementedError


class DummyMidpointService(MidpointService):
    """MCP 연동 전까지 사용할 더미 구현."""

    def suggest_meeting_areas(self, departure_points: List[str]) -> List[str]:
        # 간단히 강남역을 기본값으로 반환 (실제 구현 시 MCP/지도 API 연동)
        return ["강남역"] if departure_points else []
