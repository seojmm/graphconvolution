import json
import os
import re
from typing import List, Optional

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda
from openai import OpenAI as OpenAIClient

from ..Domain.model import (
    Constraints,
    UserRequest,
    BudgetPerPerson,
    DateRange,
    TimeRange,
    Participant,
)
from ..ports.midpoint_service import KakaoMapMidpointService


class ConstraintExtractionAgent:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.base_url = base_url or os.getenv("KANANA_BASE_URL")
        self.api_key = api_key or os.getenv("KANANA_API_KEY")
        if not self.base_url or not self.api_key:
            raise ValueError("KANANA_BASE_URL/KANANA_API_KEY must be set")
        # LangChain ChatOpenAI 클라이언트 (Kanana 호환)
        self.model_name = os.getenv("KANANA_MODEL")
        if not self.model_name:
            try:
                client = OpenAIClient(base_url=self.base_url, api_key=self.api_key)
                models = client.models.list().data
                if models:
                    self.model_name = models[0].id
            except Exception:
                self.model_name = None
        if not self.model_name:
            raise ValueError(
                "KANANA_MODEL must be set (or endpoint must list models); "
                "set KANANA_MODEL in .env to a valid model id"
            )
        self.llm = ChatOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model_name,
            temperature=0,
        )
        self.parser = StrOutputParser() | RunnableLambda(self._safe_load_json)
        # 지역명을 좌표로 변환하기 위한 KakaoMap 지오코더 (REST 키 없으면 None)
        try:
            self.geocoder = KakaoMapMidpointService()
        except Exception:
            self.geocoder = None

    def extract(self, user_request: UserRequest) -> Constraints:
        return self._extract_with_llm(user_request)

    # ------------------------------
    # LLM 연동 설계 (나중에 구현)
    # ------------------------------
    def _extract_with_llm(self, user_request: UserRequest) -> Constraints:
        """
        LLM을 통해 자연어 쿼리를 Constraints 구조로 변환.
        """
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
        - 출발지는 역 이름이 아니어도 됩니다. 사용자가 언급한 출발 위치(동/건물/랜드마크 등)를 그대로 departure_points에 담으세요.

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
        escaped_system_prompt = system_prompt.replace("{", "{{").replace("}", "}}")
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", escaped_system_prompt),
                ("user", "{user_query}"),
            ]
        )
        chain = prompt | self.llm | self.parser

        data = chain.invoke({"user_query": user_request.user_query})
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
        # area가 문자열이면 dict로 감싸서 스키마에 맞춤
        if constraints_data.get("area"):
            norm_area = []
            for a in constraints_data["area"]:
                if isinstance(a, dict):
                    norm_area.append(a)
                else:
                    norm_area.append({"name": str(a)})
            constraints_data["area"] = norm_area
        # LLM이 찾아준 출발지 우선 사용, 없으면 기존 participants에서 가져온 값으로 채움
        if not constraints_data.get("departure_points"):
            constraints_data["departure_points"] = departure_points
        # participants 리스트 보강: home_anchor를 departure_points와 1:1 매핑 시도
        dp_list = constraints_data.get("departure_points") or []
        # "string" 같은 placeholder만 있을 때는 출발지 정보가 없는 것으로 처리
        if dp_list and all(v == "string" for v in dp_list):
            dp_list = []
            constraints_data["departure_points"] = []
        participants = user_request.participants or []

        # 1) participants가 비어 있으면 departure_points 길이에 맞춰 생성
        if not participants and dp_list:
            participants = [
                Participant(participant_id=f"p{idx+1}", name=None, home_anchor=anchor)
                for idx, anchor in enumerate(dp_list)
            ]

        # 2) people_count 기반으로 필요한 수만큼 채우기
        desired_count = constraints_data.get("people_count") or len(participants) or len(dp_list)
        if desired_count > len(participants):
            start_idx = len(participants)
            for idx in range(start_idx, desired_count):
                anchor = dp_list[idx] if idx < len(dp_list) else None
                participants.append(
                    Participant(participant_id=f"p{idx+1}", name=None, home_anchor=anchor)
                )

        # 3) participants 수가 있는데 anchor가 비어 있으면 dp_list 순서대로 채움
        for idx, p in enumerate(participants):
            if dp_list and idx < len(dp_list):
                anchor = dp_list[idx]
                if not p.home_anchor or p.home_anchor == "string":
                    p.home_anchor = anchor
            # placeholder 정리
            if p.participant_id == "string":
                p.participant_id = f"p{idx+1}"
            if p.name == "string":
                p.name = None
            if p.home_anchor == "string":
                p.home_anchor = None

        user_request.participants = participants

        # meeting_point_strategy가 fixed일 때 area에 좌표 보강 시도
        if constraints_data.get("meeting_point_strategy") == "fixed" and self.geocoder and constraints_data.get("area"):
            enriched = []
            for a in constraints_data["area"]:
                entry = dict(a)
                if entry.get("name") and (not entry.get("lat") or not entry.get("lon")):
                    coord = self.geocoder._search_coords(entry["name"])
                    if coord:
                        entry["lat"] = f"{coord[0]:.6f}"
                        entry["lon"] = f"{coord[1]:.6f}"
                        entry["radius_km"] = 5.0
                # name이 없으면 빈 문자열로 통일
                entry.setdefault("name", "")
                enriched.append(entry)
            constraints_data["area"] = enriched

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
