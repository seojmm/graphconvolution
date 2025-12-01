import re
from typing import Optional

from Domain.model import (
    Constraints,
    UserRequest,
    BudgetPerPerson,
    DateRange,
    TimeRange,
)


class ConstraintExtractionAgent:
    """자연어 쿼리 -> Constraints 모델로 변환하는 에이전트.

    mode="mock"  : 정규식 기반 간단 파서 (DB 없이 로컬 테스트용)
    mode="llm"   : LLM을 이용해 Text-to-JSON 수행 (나중에 붙일 예정)
    """

    def __init__(self, mode: str = "mock"):
        if mode not in {"mock", "llm"}:
            raise ValueError("mode must be 'mock' or 'llm'")
        self.mode = mode

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
        system_prompt = """당신은 일정/장소 추천 시스템의 제약 조건 추출 에이전트입니다.
        (여기서 아까 정의한 JSON 스키마/규칙 설명 쭉...)"""
        user_prompt = user_request.user_query

        raw = self.llm_client.chat(system_prompt, user_prompt)

        # Kanana에게 "JSON만 출력해라"라고 교육해두고
        data = json.loads(raw)
        return Constraints(**data["constraints"])

        """LLM 호출을 통한 Text-to-JSON 제약 추출.

        - 시스템 프롬프트에서 JSON 스키마 명시
        - user_query를 그대로 넣고, 모델이 Constraints 형태 JSON만 출력하도록 요구
        - JSON 문자열을 파싱해서 Constraints 인스턴스로 변환

        실제 구현은 OpenAI / Anthropic SDK 등을 사용해 이 안에 넣으면 됩니다.
        """
        raise NotImplementedError("LLM 기반 제약 추출은 아직 구현되지 않았습니다.")
