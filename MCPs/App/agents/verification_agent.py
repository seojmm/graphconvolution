from typing import List
from Domain.model import Constraints, MeetingCandidate, Participant
from ports.eta_service import EtaService

#Verification Agent (Critic & Reflection)
class VerificationAgent:
    """EtaService에서 ETA 가져와서 후보가 좋은지/공평한지 판단하는 agent"""

    def __init__(self, eta_service: EtaService):
        self.eta_service = eta_service

    def evaluate(
        self,
        constraints: Constraints,
        candidates: List[MeetingCandidate],
        participants: List[Participant],
    ) -> List[MeetingCandidate]:
        for c in candidates:
            # 1) ETA 통계 계산
            eta_stats = self.eta_service.estimate_eta_stats(participants, c)
            c.eta_stats = eta_stats

            # 2) 형평성 점수 (예시: 최대 ETA가 짧을수록 좋다)
            fairness_score = self._compute_fairness_score(eta_stats)
            c.fairness_score = fairness_score

            # 3) 만족도 점수 (예시: 예산/선호도 등을 기반)
            satisfaction_score = self._compute_satisfaction_score(constraints, c)
            c.satisfaction_score = satisfaction_score

            # 4) reasoning 추가 (설명 텍스트)
            c.reasoning = (
                c.reasoning
                or f"ETA 평균 {eta_stats.avg}분, 최대 {eta_stats.max}분, 예산 및 선호도를 고려한 후보"
            )

        return candidates

    def _compute_fairness_score(self, eta_stats):
        # 아주 단순한 예시:
        # - 최대 ETA가 40분 이하면 1.0
        # - 60분 이상이면 0.0
        if eta_stats.max is None:
            return None
        if eta_stats.max <= 40:
            return 1.0
        if eta_stats.max >= 60:
            return 0.0
        # 40~60 사이 선형 보간
        return 1.0 - (eta_stats.max - 40) / 20.0

    def _compute_satisfaction_score(self, constraints: Constraints, candidate: MeetingCandidate):
        # TODO: 예산, 카테고리 선호도, soft/hard 제약 만족 여부를 기반으로 점수 계산
        # 지금은 간단히 0.8로 고정
        return 0.8
