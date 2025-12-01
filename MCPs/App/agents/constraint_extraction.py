import json
import os
import re
from typing import List, Optional

from openai import OpenAI

from ..Domain.model import (
    Constraints,
    UserRequest,
    BudgetPerPerson,
    DateRange,
    TimeRange,
)


class ConstraintExtractionAgent:
    def __init__(
        self,
        mode: str = "mock",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        if mode not in {"mock", "llm"}:
            raise ValueError("mode must be 'mock' or 'llm'")
        self.mode = mode

        # secrets are sourced from env by default to avoid hard-coding
        self.base_url = base_url or os.getenv("KANANA_BASE_URL")
        self.api_key = api_key or os.getenv("KANANA_API_KEY")
        self.client = None
        if self.mode == "llm":
            if not self.base_url or not self.api_key:
                raise ValueError("KANANA_BASE_URL/KANANA_API_KEY must be set for llm mode")
            # Kanana와 호환되는 openai 클라이언트 생성
            self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)

    def extract(self, user_request: UserRequest) -> Constraints:
        if self.mode == "mock":
            return self._extract_mock(user_request)
        return self._extract_with_llm(user_request)

    # ------------------------------
    # mock 구현: 아주 단순한 규칙 기반 파서
    # ------------------------------
    def _extract_mock(self, user_request: UserRequest) -> Constraints:
        text = user_request.user_query

        # people_count
        people_count: Optional[int] = None
        m_people = re.search(r"(\d+)\s*명", text)
        if m_people:
            people_count = int(m_people.group(1))

        # budget_per_person.max
        budget_max: Optional[int] = None
        m_budget = re.search(r"(\d+)\s*만\s*원", text)
        if m_budget:
            num = m_budget.group(1)
            # "2만원" -> 20000 가정
            budget_max = int(num) * 10000

        # area (지명 키워드 기반)
        area_keywords = ["강남", "강남역", "역삼", "선릉", "잠실", "홍대", "신촌"]
        areas = [kw for kw in area_keywords if kw in text]

        # date_range: 상대 날짜는 여기선 하드코딩 예시
        date_range = DateRange(type="single_day")
        if "금요일" in text:
            # TODO: 실제 구현에서는 호출 시점 기준 "이번 주 금요일" 계산
            date_range.start_date = "2025-11-28"
            date_range.end_date = "2025-11-28"

        # time_range
        time_range = TimeRange()
        if "저녁" in text and time_range.start_time is None:
            time_range.start_time = "18:00"
            time_range.end_time = "21:00"

        m_time = re.search(r"(\d+)\s*시", text)
        if m_time:
            hour = int(m_time.group(1))
            time_range.start_time = f"{hour:02d}:00"
            time_range.end_time = f"{(hour + 2):02d}:00"

        # category_preferences
        category_preferences = []
        if "회식" in text:
            category_preferences.append("회식")
        if "고기" in text:
            category_preferences.append("고기")
        if "술집" in text or "술" in text:
            category_preferences.append("술집")

        hard_constraints = []
        soft_constraints = []

        if people_count is not None:
            hard_constraints.append("people_count")
        if budget_max is not None:
            hard_constraints.append("budget_per_person.max")
        if date_range.start_date is not None:
            hard_constraints.append("date_range")
        if time_range.start_time is not None:
            hard_constraints.append("time_range")
        if areas:
            hard_constraints.append("area")

        if "조용" in text:
            soft_constraints.append("조용한 분위기")
        if "가성비" in text:
            soft_constraints.append("가성비 좋은 곳")

        constraints = Constraints(
            people_count=people_count,
            area=areas,
            date_range=date_range,
            time_range=time_range,
            budget_per_person=BudgetPerPerson(max=budget_max, currency="KRW"),
            category_preferences=category_preferences,
            hard_constraints=hard_constraints,
            soft_constraints=soft_constraints,
            raw_normalized_text=text,
        )
        return constraints

    # ------------------------------
    # LLM 연동 설계 (나중에 구현)
    # ------------------------------
    def _extract_with_llm(self, user_request: UserRequest) -> Constraints:
        """
        LLM을 통해 자연어 쿼리를 Constraints 구조로 변환.
        """
        if not self.client:
            # LLM 모드가 아니거나 초기화되지 않은 경우
            raise RuntimeError("LLM client is not initialized.")

        # 출발지 정보(참석자 home_anchor)를 LLM에게 전달
        departure_points: List[str] = [
            p.home_anchor for p in user_request.participants if p.home_anchor
        ]

        system_prompt = """
        당신은 모임 추천 시스템의 제약 조건 추출 에이전트입니다.
        사용자의 자연어 쿼리를 Constraints 스키마(JSON)로 변환하세요.

        케이스 안내:
        - case 1: 사용자가 특정 만남 지역을 명시한 경우 → meeting_point_strategy는 "fixed", area는 그 지역 리스트.
        - case 2: 명시된 만남 지역이 없고 참석자 출발지(home_anchor)가 여러 개 있는 경우 →
                  meeting_point_strategy는 "midpoint", departure_points에 출발지를 채우고 area는 비워둠 (중간지점 탐색을 downstream에서 수행).

        추출 대상 필드(Constraints 모델과 매핑):
        {
          "area": [string],  # 명시된 지역들
          "meeting_point_strategy": "fixed" | "midpoint",
          "departure_points": [string],  # 참석자 출발지
          "date_range": {"type": "single_day"|"multi_day"|"weekday_pattern", "start_date": "YYYY-MM-DD"|null, "end_date": "YYYY-MM-DD"|null},
          "time_range": {"start_time": "HH:MM"|null, "end_time": "HH:MM"|null},
          "people_count": int|null,
          "budget_per_person": {"max": int|null, "currency": "KRW"},
          "category_preferences": [string],
          "business_types": [string],
          "parking_required": bool|null,
          "open_until_late": bool|null,   # 새벽/늦게까지 영업 요구
          "max_travel_time": int|null,    # 분 단위 희망 최대 이동시간
          "min_rating": float|null,
          "min_review_count": int|null,
          "hard_constraints": [string],   # 반드시 지켜야 할 키
          "soft_constraints": [string],   # 선호
          "raw_normalized_text": string   # 원본 쿼리 정규화본
        }

        규칙:
        - 위 필드 외 텍스트는 출력하지 말고, JSON만 반환.
        - 값이 없으면 null 또는 빈 배열을 사용.
        - 통화는 KRW로 고정.
        """

        # 자연어 쿼리 그대로 전달 (참석자 정보가 구조화돼 있지 않아도 LLM이 출발지를 추출)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_request.user_query},
        ]

        # 모델 ID 선택: 현재 엔드포인트에서 제공하는 첫 번째 모델을 사용하거나 지정
        try:
            model_id = self.client.models.list().data[0].id  # 예: "kanana-2-30b"
        except Exception:
            model_id = "kanana-2-30b"

        # Kanana 호출
        response = self.client.chat.completions.create(
            model=model_id,
            messages=messages,
            temperature=0,
            max_tokens=1024,  # JSON이 잘리지 않도록 충분히 확보
        )

        # LLM의 응답에서 JSON 파싱
        raw_json = response.choices[0].message.content.strip()
        data = self._safe_load_json(raw_json)
        constraints_data = data.get("constraints", data)

        # meeting_point_strategy 기본값 및 출발지 반영 (case2 대비)
        if not constraints_data.get("meeting_point_strategy"):
            constraints_data["meeting_point_strategy"] = (
                "midpoint" if constraints_data.get("area") == [] and departure_points else "fixed"
            )
        # normalize list-like fields
        for key in [
            "area",
            "departure_points",
            "category_preferences",
            "business_types",
            "hard_constraints",
            "soft_constraints",
        ]:
            if constraints_data.get(key) is None:
                constraints_data[key] = []
        if not constraints_data.get("departure_points"):
            constraints_data["departure_points"] = departure_points
        constraints_data.setdefault("budget_per_person", {})  # 안전하게 기본값 준비

        return Constraints(**constraints_data)

    def _safe_load_json(self, text: str):
        """LLM 응답이 JSON만 아닐 때를 대비해 후보 문자열을 정리해서 파싱."""
        def strip_fences(s: str) -> str:
            if s.startswith("```"):
                s = s.lstrip("`")
                # 제거 후 'json' 같은 언어 태그도 제거
                s = re.sub(r"^json", "", s, flags=re.IGNORECASE).lstrip()
            if s.endswith("```"):
                s = s.rstrip("`")
            return s

        def remove_trailing_commas(s: str) -> str:
            # }], } 같은 패턴 앞의 마지막 콤마를 제거
            return re.sub(r",\s*([}\]])", r"\1", s)

        candidates = []

        cleaned = strip_fences(text.strip())
        candidates.append(cleaned)

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidates.append(cleaned[start : end + 1])

        for candidate in candidates:
            for to_try in (candidate, remove_trailing_commas(candidate)):
                try:
                    return json.loads(to_try)
                except json.JSONDecodeError:
                    continue

        raise ValueError(f"LLM 응답을 JSON으로 파싱할 수 없습니다: {text[:200]}...")
