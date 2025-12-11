from __future__ import annotations
from typing import List
from ..Domain.model import Constraints, MeetingCandidate, Participant, EtaStats
from ..ports.eta_service import EtaService
import re


#Verification Agent (Critic & Reflection)
class VerificationAgent:
    """EtaService로 ETA를 계산하고, 각 후보의 점수를 산출하는 Agent."""

    def __init__(self, eta_service: EtaService):
        self.eta_service = eta_service
        # 더미 개인화 가중치: user_id별로 스코어 가중치를 덮어쓴다.
        # 키: user_id, 값: dict(weight_fairness=..., weight_budget=..., weight_pref=..., weight_rating=...)
        self.user_weight_overrides = {
            # 예: u_001 사용자는 이동/공평성을 더 중시, 평점은 덜 중시
            "u_001": {"fairness": 0.5, "budget": 0.2, "pref": 0.15, "rating": 0.15},
            # 필요한 경우 아래에 추가
            # "user_123": {"fairness": 0.3, "budget": 0.3, "pref": 0.1, "rating": 0.3},
        }

    def evaluate(
        self,
        constraints: Constraints,
        candidates: List[MeetingCandidate],
        participants: List[Participant],
    ) -> List[MeetingCandidate]:
        """
        후보 리스트 전체를 평가한다.
        - ETA 통계(eta_stats)
        - 공평성 점수(fairness_score)
        - 예산 점수(budget_score)
        - 선호 카테고리 매칭 점수(pref_match_score)
        - 평점/리뷰 점수(rating_score)
        - 최종 점수(final_score)

        전부 여기서 계산해서 MeetingCandidate의 필드에 직접 채운다.
        """
        for candidate in candidates:
            # 1) ETA 통계 계산 (EtaService가 MCP 호출)
            eta_stats = self.eta_service.estimate_eta_stats(participants, candidate)
            candidate.eta_stats = eta_stats

            # 2) 공평성 점수
            candidate.fairness_score = self._compute_fairness_score(constraints, eta_stats)

            # 3) 서브 스코어들
            candidate.budget_score = self._compute_budget_score(constraints, candidate)
            candidate.pref_match_score = self._compute_pref_match_score(constraints, candidate)
            candidate.rating_score = self._normalize_rating_score(candidate)

            # 4) 최종 점수 계산 (가중 평균)
            terms: list[float] = []
            weights: list[float] = []

            def add(value: float | None, weight: float) -> None:
                if value is None:
                    return
                terms.append(value * weight)
                weights.append(weight)

            # 기본 가중치
            weights_cfg = {"fairness": 0.40, "budget": 0.20, "pref": 0.10, "rating": 0.30}
            # 개인화 가중치 덮어쓰기 (user_id 기준)
            user_id = getattr(constraints, "user_id", None) or getattr(constraints, "userId", None)
            if user_id and user_id in self.user_weight_overrides:
                weights_cfg.update(self.user_weight_overrides[user_id])

            add(candidate.fairness_score, weights_cfg["fairness"])
            add(candidate.budget_score, weights_cfg["budget"])
            add(candidate.pref_match_score, weights_cfg["pref"])
            add(candidate.rating_score, weights_cfg["rating"])

            candidate.final_score = (sum(terms) / sum(weights)) if weights else None

            # 5) 기본 reasoning
            if not candidate.reasoning:
                avg_str = (
                    candidate.eta_stats.avg
                    if candidate.eta_stats and candidate.eta_stats.avg is not None
                    else "?"
                )
                candidate.reasoning = (
                    f"평균 이동 시간 {avg_str}분, "
                    f"공평성·예산·선호·평점을 종합해 산출한 후보입니다."
                )

        # 점수까지 채워진 전체 후보 리스트 반환
        # Top-K 자르기는 Orchestrator에서 수행
        return candidates


    def _compute_fairness_score(
        self,
        constraints: Constraints,
        eta_stats: EtaStats | None,
    ) -> float | None:
        """
        공평성 점수 (0.0~1.0)
        - 평균 이동 시간(avg)이 짧을수록 높게,
        - 참여자 간 이동 시간 편차(std)가 작을수록 높게.
        """
        if eta_stats is None or eta_stats.avg is None:
            return None

        avg = float(eta_stats.avg)

        # 사용자가 허용 가능한 최대 이동시간이 있으면 기준으로, 없으면 30분 기준
        base = float(constraints.max_travel_time) if constraints.max_travel_time else 30.0

        # avg가 0.5*base ~ 1.5*base 구간에서 선형적으로 감소
        lower = 0.5 * base
        upper = 1.5 * base

        if avg <= lower:
            time_score = 1.0
        elif avg >= upper:
            time_score = 0.0
        else:
            time_score = (upper - avg) / (upper - lower)

        # 표준편차가 작을수록(=서로 비슷한 시간 이동) 조금 더 공평하다고 본다.
        spread_score: float | None = None
        if eta_stats.std is not None:
            std = float(eta_stats.std)
            if std <= 5:
                spread_score = 1.0
            elif std >= 20:
                spread_score = 0.0
            else:
                spread_score = (20.0 - std) / (20.0 - 5.0)

        if spread_score is None:
            return time_score

        w_time = 0.7
        w_spread = 0.3
        return (time_score * w_time + spread_score * w_spread) / (w_time + w_spread)

    


    def _compute_budget_score(
        self,
        constraints: Constraints,
        candidate: MeetingCandidate,
    ) -> float | None:
        """
        인당 예산 상한 대비 예상 가격으로 0.0~1.0 점수.
        """
        max_budget = constraints.budget_per_person.max
        price = candidate.estimated_price_per_person

        if max_budget is None or price is None:
            return None

        max_budget = float(max_budget)
        price = float(price)

        if price <= 0.5 * max_budget:
            return 0.7

        if price <= max_budget:
            return 1.0

        if price >= 1.5 * max_budget:
            return 0.5

        return (1.5 * max_budget - price) / (0.5 * max_budget)




    def _compute_pref_match_score(
        self,
        constraints: Constraints,
        candidate: MeetingCandidate,
    ) -> float | None:
        """
        선호 카테고리/업종 vs 후보 태그 매칭 정도 (0.0~1.0).
        """
        preferred = set(constraints.category_preferences or []) | set(
            constraints.business_types or []
        )
        if not preferred:
            return None

        tags: set[str] = set()

        # 후보에 붙어 있을 법한 필드들을 최대한 활용
        for attr in ("category", "sub_category", "subCategory", "business_types", "category_tags"):
            value = getattr(candidate, attr, None)
            if isinstance(value, str):
                parts = re.split(r"[>/,|]", value)
                tags.update(p.strip() for p in parts if p.strip())
            elif isinstance(value, list):
                tags.update(str(v).strip() for v in value if str(v).strip())

        if not tags:
            return None

        overlap = preferred & tags
        if not overlap:
            return 0.0

        # "요청한 것 중 얼마나 만족했는가" 기준
        return len(overlap) / len(preferred)
    


    def _normalize_rating_score(self, candidate: MeetingCandidate) -> float | None:
        """
        평점/리뷰 수 기반 품질 점수 (0.0~1.0).
        """
        rating = getattr(candidate, "rating", None)
        if rating is None:
            return None

        try:
            rating_val = float(rating)
        except (TypeError, ValueError):
            return None

        rating_val = max(0.0, min(5.0, rating_val))
        base = rating_val / 5.0

        review_count = getattr(candidate, "review_count", None) or getattr(
            candidate, "reviewCount", None
        )
        if review_count is None:
            return base

        try:
            count = int(review_count)
        except (TypeError, ValueError):
            return base

        if count <= 0:
            multiplier = 0.7
        elif count <= 10:
            multiplier = 0.7 + 0.2 * (count / 10.0)
        elif count < 100:
            multiplier = 0.9 + 0.1 * ((count - 10) / 90.0)
        else:
            multiplier = 1.0

        return base * multiplier
