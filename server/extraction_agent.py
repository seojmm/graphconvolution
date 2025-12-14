import json
import logging
import re
from typing import Dict, List

from llm_response import LLMResponse
from models import ExtractAgentRequest, ExtractAgentResponse
from tools import DaumSearchTool

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = [
    "parking",
    "breaktime",
    "openingHours",
    "closedDays",
    "priceRange",
    "menus",
    "notes",
]

KEYWORD_MAP = {
    "parking": ["주차", "주차장", "주차 가능"],
    "breaktime": ["브레이크타임", "휴게시간"],
    "openingHours": ["영업시간", "오픈시간", "영업 시간"],
    "closedDays": ["휴무", "정기휴무", "휴일"],
    "priceRange": ["가격", "가격대", "금액대"],
    "menus": ["메뉴", "추천메뉴", "시그니처"],
    "notes": ["특이사항", "비고", "참고"],
}

NOISE_PHRASES = {"없음", "정보없음", "미상"}


def _normalize_llm_result(raw: str | dict) -> dict | str:
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return raw
    if not isinstance(parsed, dict):
        return parsed
    normalized = dict(parsed)
    for key in REQUIRED_FIELDS:
        val = normalized.get(key, "")
        if val is None:
            val = ""
        if not isinstance(val, str):
            val = str(val)
        normalized[key] = val.strip()
    return normalized


def _find_missing_fields(result: dict | str) -> List[str]:
    if not isinstance(result, dict):
        return REQUIRED_FIELDS.copy()
    missing = []
    for key in REQUIRED_FIELDS:
        val = result.get(key, "")
        if not isinstance(val, str) or not val.strip():
            missing.append(key)
    return missing


def _sanitize_values(result: dict | str, noise_phrases: List[str]) -> dict | str:
    if not isinstance(result, dict):
        return result
    noise_norm = {re.sub(r"\s+", "", p.lower()) for p in noise_phrases if p}
    cleaned = dict(result)
    for key, val in list(cleaned.items()):
        if isinstance(val, str):
            norm_val = re.sub(r"\s+", "", val.lower())
            if norm_val in noise_norm:
                cleaned[key] = ""
    return cleaned


def _heuristic_fill_from_text(result: dict | str, text: str) -> dict | str:
    if not isinstance(result, dict):
        return result
    sentences = re.split(r"[\n\.\!\?]", text)
    filled = dict(result)
    for field in REQUIRED_FIELDS:
        val = filled.get(field, "")
        if isinstance(val, str) and val.strip():
            continue
        keywords = KEYWORD_MAP.get(field, [])
        match = None
        for sentence in sentences:
            for kw in keywords:
                if kw and kw in sentence:
                    match = sentence.strip()
                    break
            if match:
                break
        if match:
            filled[field] = match
    return filled


class PlaceEnrichmentAgent:
    """Agent that iteratively searches Daum and forces Kanana to fill all required fields."""

    def __init__(
        self,
        llm: LLMResponse | None = None,
        searcher: DaumSearchTool | None = None,
        base_size: int = 5,
        follow_up_size: int = 3,
    ):
        self.llm = llm or LLMResponse()
        self.searcher = searcher or DaumSearchTool()
        self.base_size = base_size
        self.follow_up_size = follow_up_size

    def _build_base_query(self, body: ExtractAgentRequest) -> str:
        tokens = [
            body.place or "",
            body.address or "",
            body.query or "",
            "주차 브레이크타임 영업시간 휴무 가격대 메뉴 비고",
        ]
        return " ".join(t for t in tokens if t).strip()

    def _build_field_query(self, body: ExtractAgentRequest, field: str) -> str:
        keywords = KEYWORD_MAP.get(field, [])
        if not keywords:
            return ""
        focus = keywords[0]
        return " ".join(
            t for t in [body.place or "", body.address or "", focus, body.query or ""] if t
        ).strip()

    def _build_prompt(self, body: ExtractAgentRequest, combined_contents: str) -> str:
        contents = combined_contents[:3000]  # 길이 제한으로 JSON 깨짐 방지
        return (
            "오직 하나의 JSON 객체만 반환하세요. 코드블록/설명/자연어 금지.\n"
            "키: parking, breaktime, openingHours, closedDays, priceRange, menus, notes\n"
            '모든 값은 문자열, 정보 없으면 빈 문자열 "" 로 설정. 추가 키 금지.\n'
            f"## 장소\n{body.place or ''} / {body.address or ''}\n\n"
            f"## 쿼리\n{body.query}\n\n"
            f"## 검색결과\n{contents}\n"
        )

    def run(self, body: ExtractAgentRequest) -> ExtractAgentResponse:
        base_query = self._build_base_query(body)
        combined, source_counts = self.searcher.collect_contents(
            base_query, sort=body.sort, page=body.page, size=body.size
        )

        prompt = self._build_prompt(body, combined)
        llm_result = _normalize_llm_result(self.llm.get_response(prompt))
        missing = _find_missing_fields(llm_result)

        attempts = 1
        extra_queries: List[str] = []
        noise_phrases = [base_query, body.query or ""]
        combined_all = combined
        counts = dict(source_counts)

        while missing and attempts < body.maxTurns:
            attempts += 1
            extra_sections: List[str] = []

            for field in missing:
                field_query = self._build_field_query(body, field)
                if not field_query:
                    continue
                extra_queries.append(field_query)
                noise_phrases.append(field_query)
                try:
                    extra_content, extra_counts = self.searcher.collect_contents(
                        field_query, sort="recency", page=1, size=self.follow_up_size
                    )
                    if extra_content:
                        extra_sections.append(f"[{field} 검색]\n{extra_content}")
                    for k, v in extra_counts.items():
                        counts[k] = counts.get(k, 0) + v
                except Exception:
                    logger.exception("Field-specific search failed", extra={"field": field})

            if extra_sections:
                combined_all = "\n\n".join([combined_all] + extra_sections).strip()

            prompt = self._build_prompt(body, combined_all)
            llm_result = _normalize_llm_result(self.llm.get_response(prompt))
            llm_result = _sanitize_values(llm_result, noise_phrases)
            llm_result = _heuristic_fill_from_text(llm_result, combined_all)
            missing = _find_missing_fields(llm_result)

        final_result = _heuristic_fill_from_text(
            _sanitize_values(llm_result, noise_phrases), combined_all
        )

        return ExtractAgentResponse(
            query=body.query,
            combinedContents=combined_all,
            llmResult=final_result,
            sourceCounts=counts,
            attempts=attempts,
            missingAfterInitial=missing,
            extraQueries=extra_queries,
        )


def run_extraction_agent(body: ExtractAgentRequest) -> ExtractAgentResponse:
    """Public entrypoint used by FastAPI and the Graphiti ingestion script."""
    agent = PlaceEnrichmentAgent()
    return agent.run(body)
