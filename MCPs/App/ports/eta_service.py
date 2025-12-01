from abc import ABC, abstractmethod
from typing import List
from ..Domain.model import Participant, MeetingCandidate, EtaStats

#KakaoMap MCP 에 직접 요청하는 레이어
class EtaService(ABC):
    """
    “각 참석자의 출발 위치(home_anchor)와 후보 장소의 위치(place 좌표)를 이용해
    지도 API(카카오맵, 네이버지도 등)로 이동 시간을 계산하고,
    그걸 평균/최대/표준편차로 요약해서 돌려주는 서비스”

    - 예: 카카오맵, 네이버지도, 구글맵 등 외부 경로 API 연동
    """

    @abstractmethod
    def estimate_eta_stats(
        self,
        participants: List[Participant],
        candidate: MeetingCandidate,
    ) -> EtaStats:
        raise NotImplementedError


class KakaoMapEtaService(EtaService):
    """로컬 테스트용 더미 구현: 고정된 ETA 통계를 반환. 나중에 카카오맵 받아서 수정 필요"""

    def estimate_eta_stats(
        self,
        participants: List[Participant],
        candidate: MeetingCandidate,
    ) -> EtaStats:
        # 실제로는 거리/교통정보 기반 계산 필요
        return EtaStats(avg=20, max=35, std=5.0)
