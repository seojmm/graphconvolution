"""FastAPI service that proxies Kakao Map place searches."""

from datetime import datetime
import asyncio
import html
import json
import logging
import os
import re
import sys
import ast
from typing import List, Optional, Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
import requests
from pydantic import BaseModel

# Allow same-directory imports without package prefix (e.g., `import models`).
BASE_DIR = os.path.dirname(__file__)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Also allow importing sibling packages (e.g., `MCPs`) when running `python server/main.py`.
REPO_ROOT = os.path.dirname(BASE_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from graphiti_core import Graphiti
from kakao_data_collector import KakaoDataCollector
from llm_response import LLMResponse
import graphiti_agent as graph_agent
from models import (
    CategoryGroupCode,
    DaumBlogResult,
    DaumCafeResult,
    DaumWebResult,
    ExtractResponse,
    KakaoGeocodeResult,
    KakaoPlace,
    PlaceData,
    PlacesResponse,
    ExtractAgentRequest,
    ExtractAgentResponse,
)
from MCPs.App.Domain.model import (
    OrchestratorResult as MCPOrchestratorResult,
    MeetingCandidate as MCPMeetingCandidate,
    ScheduleRequest as MCPScheduleRequest,
    ScheduleResult as MCPScheduleResult,
    UserRequest as MCPUserRequest,
)
from extraction_agent import run_extraction_agent



logger = logging.getLogger(__name__)
collector = KakaoDataCollector()
kanana_client = LLMResponse()
graph_client: Graphiti | None = None

app = FastAPI(title="Kakao Places Proxy", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

Intent = Literal["place_search", "general", "suspicious", "meeting_place", "place_recommendation"]
AgentMode = Literal["agent"]
AgentIntent = Literal["general", "meeting_place", "place_recommendation"]


class ChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    meta: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    mode: Optional[AgentMode] = None
    conversationId: Optional[str] = None
    history: List[ChatHistoryMessage] = []


class ChatResponse(BaseModel):
    intent: Intent
    reply: str
    suggestions: Optional[List[str]] = None
    agent: Optional[dict] = None
    meta: dict | None = None


class MemoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class KananaQARequest(BaseModel):
    user_query: str
    memory: List[MemoryMessage] = []
    user_id: str = "web"


class KananaQAResponse(BaseModel):
    reply: str
    memory: List[MemoryMessage]
    candidates: Optional[List[MCPMeetingCandidate]] = None
    orchestrator: Optional[MCPOrchestratorResult] = None
    suggestions: Optional[List[str]] = None


_mcp_orchestrator = None


BOT_PURPOSE = "충분한 제약조건을 입력받아 약속 장소를 추천해주는 챗봇"


def _looks_like_meeting_place_query(text: str) -> bool:
    lowered = (text or "").lower()
    keywords = [
        "약속",
        "만날",
        "모임",
        "회식",
        "데이트",
        "장소",
        "추천",
        "맛집",
        "식당",
        "카페",
        "어디",
        "중간",
        "역",
        "지역",
        "인원",
        "명",
        "예산",
        "가격",
        "시간",
        "날짜",
        "주차",
    ]
    return any(k in lowered for k in keywords)


def _user_said_no_preference(text: str) -> bool:
    lowered = (text or "").lower().replace(" ", "")
    phrases = [
        "상관없",
        "아무거나",
        "다괜찮",
        "상관없다고",
        "신경안써",
        "알아서",
    ]
    return any(p in lowered for p in phrases)


def _count_mentions_in_memory(memory: List[MemoryMessage], needles: List[str], role: str) -> int:
    count = 0
    for msg in memory or []:
        if msg.role != role:
            continue
        content = msg.content or ""
        if any(n in content for n in needles):
            count += 1
    return count


def _build_kanana_behavior_notes(user_query: str, memory: List[MemoryMessage]) -> str:
    notes: List[str] = []

    if _user_said_no_preference(user_query):
        notes.append("사용자가 '상관없어/아무거나'라고 말한 항목은 기본값으로 가정하고 다시 묻지 말 것.")
        notes.append("추가 질문 대신, 현재까지 정보로 3개 후보를 먼저 제안할 것.")

    asked_budget = _count_mentions_in_memory(memory, ["예산", "1인", "만원", "가격"], role="assistant")
    asked_parking = _count_mentions_in_memory(memory, ["주차"], role="assistant")
    asked_vibe = _count_mentions_in_memory(memory, ["조용", "활기", "분위기"], role="assistant")

    if asked_budget + asked_parking + asked_vibe >= 2:
        notes.append("같은 질문을 반복하지 말고, 현재까지 정보로 우선 추천을 제시할 것.")

    return "\n".join(f"- {n}" for n in notes).strip()


def _extract_first_json_object_relaxed(text: str) -> dict | None:
    parsed = _extract_first_json_object(text)
    if parsed is not None:
        return parsed
    if not text:
        return None
    try:
        candidate = json.loads(text)
    except Exception:
        return None
    return candidate if isinstance(candidate, dict) else None


def _build_orchestrate_readiness_prompt(user_query: str, memory: List[MemoryMessage], limit: int = 20) -> str:
    trimmed = memory[-limit:] if memory else []
    lines: List[str] = []
    for msg in trimmed:
        role = "사용자" if msg.role == "user" else "어시스턴트"
        content = (msg.content or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    memory_text = "\n".join(lines).strip()

    return (
        f"당신은 {BOT_PURPOSE}입니다.\n"
        "지금까지의 대화를 보고, 장소 추천을 바로 진행해도 될지 판단하세요.\n\n"
        "반드시 JSON 1개만 반환하세요(코드블록/설명 금지).\n"
        "스키마:\n"
        "{\n"
        '  "ready": true|false,\n'
        '  "missing": ["지역/역", "날짜/시간대", "인원", "예산(1인)", "종류(식당/카페)"],\n'
        '  "assembled_user_query": "오케스트레이터(/orchestrate)에 전달할 자연어 쿼리"\n'
        "}\n\n"
        "규칙:\n"
        "- ready=true: 최소한 지역/역(또는 출발지), 인원, 종류(식당/카페)가 확보됐고 추천을 시작할 수 있을 때.\n"
        "- 사용자가 '상관없어/아무거나'라고 말한 항목은 missing에 넣지 말 것.\n"
        "- assembled_user_query에는 지금까지의 선호(예: 딸기 디저트, 조용하게, 강남역 근처)를 자연스럽게 포함.\n\n"
        f"대화 기록:\n{memory_text if memory_text else '(없음)'}\n\n"
        f"이번 사용자 메시지:\n{user_query}\n"
    )


def _format_candidates_for_reply(candidates: List[MCPMeetingCandidate]) -> str:
    lines: List[str] = []
    for idx, cand in enumerate(candidates[:3], start=1):
        price = f" · 1인 {cand.estimated_price_per_person}원" if cand.estimated_price_per_person else ""
        lines.append(f"{idx}. {cand.place_name} ({cand.address}){price}")
    return "\n".join(lines).strip()


def _memory_contains_text(memory: List[MemoryMessage], text: str) -> bool:
    target = (text or "").strip()
    if not target:
        return False
    return any((m.content or "").strip() == target for m in (memory or []))


def _build_demo_candidates(time_label: str) -> List[MCPMeetingCandidate]:
    base_date = "2025-12-19"  # 데모용 고정 (이번 주 금요일)
    start_time = f"{base_date}T{time_label}:00+09:00"
    end_hour, end_min = time_label.split(":")
    end_time = f"{base_date}T{end_hour}:{end_min}:00+09:00"

    demo = [
        ("안남숯불", "서울 강남구 테헤란로24길 31"),
        ("서진식당", "서울 강남구 테헤란로84길 33"),
        ("퇴벤돈까스", "서울 강남구 테헤란로 124"),
        ("강남밥상 강남역점", "서울 서초구 서초대로77길 24"),
        ("닭터홈 강남본점", "서울 강남구 역삼로3길 17"),
        ("감성타코 강남역점", "서울 강남구 강남대로 406"),
        ("딘타이펑 강남점", "서울 서초구 서초대로73길 12"),
        ("이대비엔나식당", "서울 강남구 사평대로52길 13"),
        ("강남부칼국수", "서울 서초구 서초대로74길 23"),
        ("마라공방 강남역점", "서울 강남구 강남대로84길 6"),
    ]

    candidates: List[MCPMeetingCandidate] = []
    for idx, (name, address) in enumerate(demo, start=1):
        candidates.append(
            MCPMeetingCandidate(
                id=f"demo_{idx}",
                request_id="demo_req",
                place_name=name,
                place_id=f"demo_place_{idx}",
                address=address,
                start_time=start_time,
                end_time=end_time,
                estimated_price_per_person=18000,
                reasoning="demo",
            )
        )
    return candidates


def _redirect_to_purpose_reply(user_query: str) -> str:
    snippet = (user_query or "").strip()
    if snippet:
        snippet = snippet[:80]
    return (
        "좋아요. 그럼 그걸 약속에 반영해서 장소를 잡아볼게요.\n"
        "어느 지역/역에서 만날까요? 그리고 몇 명이에요?\n"
        "예: “오늘 저녁 7시 강남역, 2명, 1인 2만원, 영화관 근처에서”"
    )


def _get_mcp_orchestrator():
    global _mcp_orchestrator
    if _mcp_orchestrator is not None:
        return _mcp_orchestrator

    from dotenv import load_dotenv

    load_dotenv(".env.local")

    from MCPs.App.agents.action_agent import ActionAgent
    from MCPs.App.agents.constraint_extraction import ConstraintExtractionAgent
    from MCPs.App.agents.knowledge_agent import KnowledgeAgent
    from MCPs.App.agents.planning_agent import PlanningAgent
    from MCPs.App.agents.verification_agent import VerificationAgent
    from MCPs.App.orchestrator.orchestrator import Orchestrator
    from MCPs.App.ports.calender_gateway import KakaoCalenderGateway, KakaoMemoChatGateway, KakaoMapGateway
    from MCPs.App.ports.eta_service import KakaoMapEtaService
    from MCPs.App.ports.meeting_repository import InMemoryMeetingRepository
    from MCPs.App.ports.midpoint_service import KakaoMapMidpointService
    from MCPs.kakao_mcp import PlayMCPClient
    from MCPs.tools.mcp_tools import set_mcp_client

    play_mcp_toolbox_url = (
        os.getenv("PLAY_MCP_ENDPOINT")
        or os.getenv("PLAY_MCP_TOOLBOX_URL")
        or "https://playmcp.kakao.com/mcp"
    )

    constraint_agent = ConstraintExtractionAgent()
    meeting_repo = InMemoryMeetingRepository()
    knowledge_agent = KnowledgeAgent(meeting_repository=meeting_repo)
    verification_agent = VerificationAgent(eta_service=KakaoMapEtaService())

    talk_calender_client = PlayMCPClient(base_url=play_mcp_toolbox_url or "")
    try:
        talk_calender_client.initialize(client_name="graphconvolution", client_version="0.1.0")
        logger.info("PlayMCP initialize completed.")
    except Exception as exc:
        logger.warning("PlayMCP initialize failed: %s", exc)

    set_mcp_client(talk_calender_client)

    calender_gateway = KakaoCalenderGateway(talk_calender_client=talk_calender_client)
    memo_gateway = KakaoMemoChatGateway(client=talk_calender_client)
    map_gateway = KakaoMapGateway(client=talk_calender_client)
    action_agent = ActionAgent(
        calender_gateway=calender_gateway,
        memo_gateway=memo_gateway,
        map_gateway=map_gateway,
        llm=getattr(constraint_agent, "llm", None),
    )

    kakao_rest_key = os.getenv("KAKAO_REST_API_KEY")
    midpoint_service = KakaoMapMidpointService(rest_api_key=kakao_rest_key) if kakao_rest_key else None

    planning_agent = PlanningAgent(
        constraint_agent=constraint_agent,
        knowledge_agent=knowledge_agent,
        verification_agent=verification_agent,
        midpoint_service=midpoint_service,
    )

    _mcp_orchestrator = Orchestrator(
        planning_agent=planning_agent,
        action_agent=action_agent,
    )
    return _mcp_orchestrator


def _extract_first_json_object(text: str) -> dict | None:
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.IGNORECASE)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = cleaned[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _format_history_for_prompt(history: List[ChatHistoryMessage], limit: int = 8) -> str:
    turns = history[-limit:] if history else []
    lines: List[str] = []
    for msg in turns:
        role = "사용자" if msg.role == "user" else "어시스턴트"
        content = (msg.content or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines).strip()


def _build_kanana_pivot_prompt(user_query: str, memory: List[MemoryMessage], limit: int = 20) -> str:
    trimmed = memory[-limit:] if memory else []
    lines: List[str] = []

    for msg in trimmed:
        role = "사용자" if msg.role == "user" else "어시스턴트"
        content = (msg.content or "").strip()
        if content:
            lines.append(f"{role}: {content}")

    memory_text = "\n".join(lines).strip()
    behavior_notes = _build_kanana_behavior_notes(user_query, trimmed)
    extra_rules = f"추가 규칙:\n{behavior_notes}\n\n" if behavior_notes else ""
    return (
        f"당신은 {BOT_PURPOSE}입니다.\n"
        "사용자의 말이 약속 장소와 직접 관련이 없어도, 이를 '약속에서 하고 싶은 활동/분위기/선호'로 자연스럽게 해석해 이어가세요.\n\n"
        "출력 규칙:\n"
        "- 한국어로, 딱딱한 소개(예: “저는 ~챗봇입니다”)는 피하세요.\n"
        "- 사용자의 말에 1문장 정도 공감/반응한 뒤, 약속 장소 추천을 위해 필요한 질문을 1~2개만 하세요.\n"
        "- 질문은 선택지를 주듯이 짧게(예: “어느 지역에서?” “몇 명이에요?”).\n"
        "- JSON/코드블록 금지.\n\n"
        f"{extra_rules}"
        f"대화 기록:\n{memory_text if memory_text else '(없음)'}\n\n"
        f"이번 사용자 메시지:\n{user_query}\n"
    )


def _build_kanana_qa_prompt(user_query: str, memory: List[MemoryMessage], limit: int = 20) -> str:
    trimmed = memory[-limit:] if memory else []
    lines: List[str] = []

    for msg in trimmed:
        role = "사용자" if msg.role == "user" else "어시스턴트"
        content = (msg.content or "").strip()
        if content:
            lines.append(f"{role}: {content}")

    memory_text = "\n".join(lines).strip()
    behavior_notes = _build_kanana_behavior_notes(user_query, trimmed)
    extra_rules = f"추가 규칙:\n{behavior_notes}\n\n" if behavior_notes else ""
    return (
        f"당신은 {BOT_PURPOSE}입니다.\n"
        "아래 '대화 기록'을 참고해서, '사용자 질문'에 자연스럽고 도움이 되게 답변하세요.\n"
        "행동 원칙:\n"
        "- 사용자의 질문이 약속 장소 추천과 무관하면, 이를 '약속에서 하고 싶은 활동/분위기/선호'로 자연스럽게 연결해서 1~2개만 추가 질문하세요.\n"
        "- 약속 장소 추천과 관련 있으면, 대화 기록을 기반으로 이미 나온 제약조건은 재사용하고 부족한 것만 1~3개로 좁혀 질문하세요.\n"
        "- 제약조건 예: 만날 지역/역(또는 출발지), 인원, 예산(1인), 날짜/시간, 카테고리(식당/카페), 주차/알레르기/제외 조건.\n"
        "- 답변은 한국어, 너무 길게 쓰지 말고(최대 6문장), JSON/코드블록은 출력하지 마세요.\n\n"
        f"{extra_rules}"
        f"대화 기록:\n{memory_text if memory_text else '(없음)'}\n\n"
        f"사용자 질문:\n{user_query}\n"
    )


def _agent_fallback(message: str) -> dict:
    lowered = (message or "").lower()
    if any(kw in lowered for kw in ["핫플", "핫한", "요즘", "추천", "맛집", "카페", "어디가", "어디야"]):
        return {
            "intent": "place_recommendation",
            "reply": (
                "어느 지역 기준으로 찾고 있어요? 예: 강남/홍대/성수/을지로/해운대 처럼요.\n"
                "지역이 정해지면 그 주변에서 요즘 인기 많은 분위기/종류(카페·식당·바)까지 맞춰서 추천해드릴게요."
            ),
            "suggestions": ["서울", "강남", "홍대", "성수", "을지로", "부산"],
        }

    return {
        "intent": "general",
        "reply": "어떤 목적(약속 장소 정하기/핫플 추천/일반 질문)인지 조금만 더 알려주면 더 정확히 도와드릴게요.",
        "suggestions": ["약속 장소 정하기 도와줘", "요즘 핫플 추천해줘", "식당 추천해줘"],
    }


def _agent_llm_decide(message: str, history: List[ChatHistoryMessage]) -> dict:
    history_text = _format_history_for_prompt(history)
    prompt = (
        "당신은 사용자와 대화하며 다음 행동을 결정하는 챗봇 에이전트입니다.\n"
        "사용자가 원하면 '약속 장소 정하기'도 도와주고, 그렇지 않으면 일반 대화/핫플 추천처럼 자연스럽게 답하세요.\n\n"
        "반드시 JSON 1개만 반환하세요. 코드블록/설명/자연어 금지.\n"
        "스키마:\n"
        "{\n"
        '  "intent": "general" | "meeting_place" | "place_recommendation",\n'
        '  "reply": "자연스러운 한국어 답변(최대 5문장)",\n'
        '  "suggestions": ["사용자가 클릭할 수 있는 짧은 문장"]\n'
        "}\n\n"
        "규칙:\n"
        "- intent=place_recommendation: '요즘 핫한 장소/핫플/추천'처럼 지역/취향이 불명확하면 먼저 1~2개 질문으로 좁히고, suggestions로 지역/카테고리 예시를 3~6개 제시.\n"
        "- intent=meeting_place: 약속 장소를 정하려는 맥락이면 필요한 정보(지역/인원/예산/시간/종류)를 우선 물어보고 suggestions로 입력 템플릿을 제시. 정보가 충분하면 후보 3개를 자연어로 제시하고 suggestions는 빈 배열.\n"
        "- intent=general: 일반 질문이면 자연스럽게 답하고, 필요하면 약속 장소 기능을 한 문장으로만 안내. suggestions는 필요할 때만.\n\n"
        f"대화 기록:\n{history_text if history_text else '(없음)'}\n\n"
        f"이번 사용자 메시지:\n{message}\n"
    )

    raw = kanana_client.get_response(prompt, temperature=0.3)
    parsed = _extract_first_json_object(raw)
    if not parsed:
        return _agent_fallback(message)

    intent = parsed.get("intent")
    reply = parsed.get("reply")
    suggestions = parsed.get("suggestions")

    if intent not in ("general", "meeting_place", "place_recommendation"):
        return _agent_fallback(message)
    if not isinstance(reply, str) or not reply.strip():
        return _agent_fallback(message)

    normalized_suggestions: List[str] = []
    if isinstance(suggestions, list):
        for item in suggestions:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    normalized_suggestions.append(text)
    normalized_suggestions = normalized_suggestions[:6]

    return {"intent": intent, "reply": reply.strip(), "suggestions": normalized_suggestions}


async def _get_graph_client() -> Graphiti:
    """Lazily create a Graphiti client for Graph RAG queries."""
    global graph_client
    if graph_client is not None:
        return graph_client

    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USERNAME") or os.getenv("NEO4J_USER")
    pwd = os.getenv("NEO4J_PASSWORD")
    if not uri or not user or not pwd:
        raise HTTPException(status_code=500, detail="NEO4J connection is not configured.")

    client = Graphiti(uri, user, pwd)
    await client.build_indices_and_constraints()
    graph_client = client
    return client


def _ensure_api_key() -> None:
    if not collector.kakao_api_key:
        raise HTTPException(status_code=500, detail="KAKAO_REST_API_KEY is not configured.")


def _validate_inputs(region: str, district: str, categories: List[str]) -> None:
    region_info = collector.regions.get(region)
    if not region_info:
        raise HTTPException(status_code=404, detail=f"Region '{region}' is not supported.")

    if district not in region_info["districts"]:
        raise HTTPException(status_code=404, detail=f"District '{district}' is not listed for region '{region}'.")

    invalid_categories = [c for c in categories if c not in collector.category_mapping]
    if invalid_categories:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown categories requested: {', '.join(invalid_categories)}",
        )


def _ensure_llm_key() -> None:
    if not kanana_client.kanana_api_key:
        raise HTTPException(status_code=500, detail="KANANA_API_KEY is not configured.")


def _collect_places(region: str, district: str, categories: List[str]) -> List[PlaceData]:
    _ensure_api_key()
    _validate_inputs(region, district, categories)

    collected = []
    for category in categories:
        collected.extend(collector.collect_kakao_data(region, district, category))

    unique = collector._deduplicate_restaurants(collected)
    # Validate/normalize against the response schema early
    validated: List[PlaceData] = [PlaceData(**item) for item in unique]
    return validated


def _kakao_request(path: str, params: dict) -> dict:
    _ensure_api_key()
    url = f"https://dapi.kakao.com{path}"
    headers = {"Authorization": f"KakaoAK {collector.kakao_api_key}"}
    response = requests.get(url, headers=headers, params=params, timeout=10)
    try:
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        detail = response.text if "response" in locals() else str(exc)
        raise HTTPException(status_code=502, detail=f"Kakao API request failed: {detail}") from exc


def _daum_request(path: str, params: dict) -> dict:
    _ensure_api_key()
    url = f"https://dapi.kakao.com{path}"
    headers = {"Authorization": f"KakaoAK {collector.kakao_api_key}"}
    response = requests.get(url, headers=headers, params=params, timeout=10)
    try:
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        detail = response.text if "response" in locals() else str(exc)
        raise HTTPException(status_code=502, detail=f"Kakao API request failed: {detail}") from exc
    

def _parse_geocode(doc: dict) -> KakaoGeocodeResult:
    address_name = doc.get("address_name", "") or (doc.get("address") or {}).get("address_name", "")
    road_name = (doc.get("road_address") or {}).get("address_name", "")
    y = doc.get("y") or (doc.get("address") or {}).get("y") or 0
    x = doc.get("x") or (doc.get("address") or {}).get("x") or 0
    return KakaoGeocodeResult(
        addressName=address_name,
        roadAddressName=road_name,
        latitude=float(y),
        longitude=float(x),
        raw=doc,
    )


def _collect_daum_contents(query: str, sort: str, page: int, size: int) -> tuple[str, dict]:
    params = {"query": query, "sort": sort, "page": page, "size": size}

    web = _daum_request("/v2/search/web", params)
    blog = _daum_request("/v2/search/blog", params)
    cafe = _daum_request("/v2/search/cafe", params)

    def _clean(text: str) -> str:
        no_tags = re.sub(r"<[^>]+>", " ", text or "")
        return re.sub(r"\s+", " ", html.unescape(no_tags)).strip()

    focus_terms = [t for t in query.split() if t][:2]

    contents = []
    for dataset in (web, blog, cafe):
        for doc in dataset.get("documents", []):
            title = _clean(doc.get("title", ""))
            body = _clean(doc.get("contents", ""))
            combined_doc = f"{title}\n{body}".strip()
            if not combined_doc:
                continue
            if focus_terms and not any(term in combined_doc for term in focus_terms):
                continue
            contents.append(combined_doc)

    if not contents:
        for dataset in (web, blog, cafe):
            for doc in dataset.get("documents", []):
                title = _clean(doc.get("title", ""))
                body = _clean(doc.get("contents", ""))
                combined_doc = f"{title}\n{body}".strip()
                if combined_doc:
                    contents.append(combined_doc)

    source_counts = {
        "web": len(web.get("documents", [])),
        "blog": len(blog.get("documents", [])),
        "cafe": len(cafe.get("documents", [])),
    }

    combined = "\n\n".join(contents).strip()
    return combined, source_counts



@app.get("/regions")
async def list_regions():
    return {"regions": collector.regions, "categories": list(collector.category_mapping.keys())}


@app.get("/places", response_model=PlacesResponse)
async def get_places(
    region: str = Query(..., description="Region key such as 'seoul' or 'gyeonggi'."),
    district: str = Query(..., description="District name that exists in the chosen region."),
    category: Optional[List[str]] = Query(
        None, description="Optional category filter. If omitted, all known categories are fetched."
    ),
):
    categories = category or list(collector.category_mapping.keys())

    try:
        items = await run_in_threadpool(_collect_places, region, district, categories)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch places from Kakao API.")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return PlacesResponse(region=region, district=district, categories=categories, total=len(items), items=items)


@app.get("/kakao/geocode/address", response_model=KakaoGeocodeResult)
async def kakao_geocode_address(query: str = Query(..., description="Full address text.")):
    try:
        data = await run_in_threadpool(_kakao_request, "/v2/local/search/address.json", {"query": query})
    except HTTPException:
        raise
    documents = data.get("documents") or []
    if not documents:
        raise HTTPException(status_code=404, detail="No address results.")
    return _parse_geocode(documents[0])


@app.get("/kakao/geocode/coord2address", response_model=KakaoGeocodeResult)
async def kakao_geocode_coord(
    lat: float = Query(..., description="Latitude (y)."),
    lng: float = Query(..., description="Longitude (x)."),
):
    try:
        data = await run_in_threadpool(
            _kakao_request,
            "/v2/local/geo/coord2address.json",
            {"y": lat, "x": lng},
        )
    except HTTPException:
        raise
    documents = data.get("documents") or []
    if not documents:
        raise HTTPException(status_code=404, detail="No address results.")
    return _parse_geocode(documents[0])


@app.get("/kakao/place/search", response_model=List[KakaoPlace])
async def kakao_place_search(
    query: str = Query(..., description="검색을 원하는 질의어"),
    category_group_code: CategoryGroupCode = Query(None, description="카테고리 그룹 코드, 카테고리로 결과 필터링을 원하는 경우 사용"),
    x: Optional[float] = Query(None, description="중심 좌표의 X 혹은 경도(longitude) 값"),
    y: Optional[float] = Query(None, description="중심 좌표의 Y 혹은 위도(latitude) 값"),
    radius: Optional[int] = Query(None, description="중심 좌표부터의 반경거리. 특정 지역을 중심으로 검색하려고 할 경우 중심좌표로 쓰일 x,y와 함께 사용(단위: 미터(m), 최소: 0, 최대: 20000)"),
    size: int = Query(15, ge=1, le=15, description="한 페이지에 보여질 문서의 개수(최소: 1, 최대: 15, 기본값: 15)"),
):
    params = {"query": query, "size": size}
    if x is not None and y is not None:
        params.update({"x": x, "y": y})
        if radius is not None:
            params["radius"] = radius
    if category_group_code is not None:
        params["category_group_code"] = category_group_code.value

    try:
        data = await run_in_threadpool(_kakao_request, "/v2/local/search/keyword.json", params)
    except HTTPException:
        raise

    documents = data.get("documents") or []
    results: List[KakaoPlace] = []
    for doc in documents:
        distance_val = doc.get("distance")
        distance = None
        if distance_val not in (None, ""):
            distance = str(distance_val)
        results.append(
            KakaoPlace(
                id=doc.get("id", ""),
                placeName=doc.get("place_name", ""),
                placeUrl=doc.get("place_url", "") or "",
                categoryName=doc.get("category_name", ""),
                categoryGroupCode=doc.get("category_group_code", "") or "",
                categoryGroupName=doc.get("category_group_name", "") or "",
                phone=doc.get("phone", "") or "",
                addressName=doc.get("address_name", "") or "",
                roadAddressName=doc.get("road_address_name", "") or "",
                longitude=float(doc.get("x", 0)),
                latitude=float(doc.get("y", 0)),
                distance=distance,
            )
        )
    return results


@app.get("/daum/search/web", response_model=DaumWebResult)
async def daum_web_search(
    query: str = Query(..., description="Search query."),
    sort: str = Query("recency", description="Sort by 'accuracy' or 'recency'."),
    page: int = Query(1, ge=1, le=50, description="Page number."),
    size: int = Query(5, ge=1, le=50, description="Number of results per page."),
):
    try:
        data = await run_in_threadpool(
            _daum_request,
            "/v2/search/web",
            {"query": query, "sort": sort, "page": page, "size": size},
        )
    except HTTPException:
        raise

    return DaumWebResult(meta=data.get("meta", {}), documents=data.get("documents", []))


@app.get("/daum/search/blog", response_model=DaumBlogResult)
async def daum_blog_search(
    query: str = Query(..., description="Search query."),
    sort: str = Query("recency", description="Sort by 'accuracy' or 'recency'."),
    page: int = Query(1, ge=1, le=50, description="Page number."),
    size: int = Query(10, ge=1, le=50, description="Number of results per page."),
):
    try:
        data = await run_in_threadpool(
            _daum_request,
            "/v2/search/blog",
            {"query": query, "sort": sort, "page": page, "size": size},
        )
    except HTTPException:
        raise

    return DaumBlogResult(meta=data.get("meta", {}), documents=data.get("documents", []))

@app.get("/daum/search/cafe", response_model=DaumCafeResult)
async def daum_cafe_search(
    query: str = Query(..., description="Search query."),
    sort: str = Query("recency", description="Sort by 'accuracy' or 'recency'."),
    page: int = Query(1, ge=1, le=50, description="Page number."),
    size: int = Query(10, ge=1, le=50, description="Number of results per page."),
):
    try:
        data = await run_in_threadpool(
            _daum_request,
            "/v2/search/cafe",
            {"query": query, "sort": sort, "page": page, "size": size},
        )
    except HTTPException:
        raise

    return DaumCafeResult(meta=data.get("meta", {}), documents=data.get("documents", []))  


@app.get("/extract", response_model=ExtractResponse)
async def extract_information(
    query: str = Query(..., description="Search query forwarded to Daum web/blog/cafe."),
    sort: str = Query("accuracy", description="Sort by 'accuracy' or 'recency'."),
    page: int = Query(1, ge=1, le=5, description="Page number (kept small to limit payload)."),
    size: int = Query(10, ge=1, le=10, description="Results per source to aggregate."),
):
    _ensure_llm_key()

    try:
        combined, source_counts = await run_in_threadpool(_collect_daum_contents, query, sort, page, size)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to collect Daum contents.")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not combined:
        raise HTTPException(status_code=404, detail="No contents found from Daum searches.")

    system_prompt = (
        "너는 한 장소(쿼리에 포함된 상호/주소)에 대한 정보만 추출한다. "
        "입력은 Daum web/blog/cafe 검색 결과 텍스트이며 HTML 태그가 제거되어 있다. "
        "출력은 JSON 객체 하나뿐이다. 코드블록, 예시 복사, 자연어 설명, 추가 문장은 모두 금지. "
        "## 출력 JSON key 설명\n"
        "parking: 주차 가능 여부 및 관련 정보 (str)\n"
        "breaktime: 브레이크타임 정보 (str)\n"
        "openingHours: 영업 시간 정보 (str)\n"
        "closedDays: 휴무일 정보 (str)\n"
        "priceRange: 가격대 정보 (str)\n"
        "menus: 주요 메뉴 정보 (str)\n"
        "notes: 기타 참고할 만한 정보 (str)\n"
        "rating: 평점 (float)\n"
        "description: 장소에 대한 간단한 설명 (str)\n"
        "isOpen: 현재 영업 중인지 여부 (bool)\n"
        "\n"
        "필수 키: parking, breaktime, openingHours, closedDays, priceRange, menus, notes (정보 없으면 None). "
        "추가로 유용한 정보가 있으면 임의 키를 넣을 수 있지만, JSON 외 다른 형식은 절대 포함하지 마라. "
    )
    prompt = (
        f"{system_prompt}\n"
        f"## 쿼리\n{query}\n\n"
        f"## 연결된 contents\n{combined}\n\n"
        "위 내용 중 쿼리와 관련된 정보를 JSON으로 추출해. "
    )
    
    llm_output = await run_in_threadpool(kanana_client.get_response, prompt)
    
    parsed: dict | str
    try:
        parsed = json.loads(llm_output)
    except Exception:
        parsed = llm_output

    required_keys = ["parking", "breaktime", "openingHours", "closedDays", "menus", "notes"]
    if isinstance(parsed, dict):
        normalized = dict(parsed)
        for key in required_keys:
            val = normalized.get(key, "")
            if val is None:
                val = ""
            if not isinstance(val, str):
                val = str(val)
            normalized[key] = val
        parsed = normalized

    return ExtractResponse(
        query=query,
        combinedContents=combined,
        llmResult=parsed,
        sourceCounts=source_counts,
    )


EXTRACT_AGENT_RESPONSE_EXAMPLES = {
    "single_turn_filled": {
        "summary": "1회 호출로 필드가 모두 채워진 경우",
        "value": {
            "query": "강남역 근처 파스타 맛집 정보 추출",
            "combinedContents": "[DAUM_WEB] ...\n[DAUM_BLOG] ...",
            "llmResult": {
                "parking": "건물 지하 주차 가능(2시간 무료)",
                "breaktime": "15:00~17:00",
                "openingHours": "매일 11:30~22:00",
                "closedDays": "연중무휴",
                "priceRange": "1인 15,000~25,000원",
                "menus": "트러플 크림 파스타 18,000원; 봉골레 17,000원",
                "notes": "예약 가능, 단체석 있음",
            },
            "sourceCounts": {"web": 3, "blog": 2, "cafe": 0},
            "attempts": 1,
            "missingAfterInitial": [],
            "extraQueries": [],
        },
    },
    "multi_turn_with_followups": {
        "summary": "부족 필드를 키워드 확장 검색으로 보완한 경우",
        "value": {
            "query": "을지로 카페 영업시간/휴무/주차 정보",
            "combinedContents": "[DAUM_WEB] ...\n\n[openingHours 검색]\n...\n\n[parking 검색]\n...",
            "llmResult": {
                "parking": "인근 공영주차장 이용(도보 3분)",
                "breaktime": "",
                "openingHours": "매일 10:00~22:00",
                "closedDays": "매주 월요일",
                "priceRange": "음료 5,000~8,000원",
                "menus": "아메리카노 5,000원; 라떼 6,000원",
                "notes": "노키즈존, 좌석이 적어 피크타임 대기 가능",
            },
            "sourceCounts": {"web": 4, "blog": 3, "cafe": 1},
            "attempts": 2,
            "missingAfterInitial": ["breaktime"],
            "extraQueries": [
                "영업시간 을지로 카페 영업시간/휴무/주차 정보",
                "주차 을지로 카페 영업시간/휴무/주차 정보",
            ],
        },
    },
}


@app.post(
    "/extract/agent",
    response_model=ExtractAgentResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "examples": EXTRACT_AGENT_RESPONSE_EXAMPLES,
                }
            }
        }
    },
)
async def extract_agent(body: ExtractAgentRequest):
    """Agentic extractor: 기본 검색 후 부족 필드를 키워드 확장 검색으로 채운다."""
    _ensure_llm_key()
    try:
        result = await run_in_threadpool(run_extraction_agent, body)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Agentic extract failed.")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result





# ------------------------------
# MCP Orchestrator endpoints (unified)
# ------------------------------


@app.post("/orchestrate", response_model=MCPOrchestratorResult)
async def orchestrate(body: MCPUserRequest):
    """Plan meeting candidates using the MCP orchestrator."""
    orchestrator = await run_in_threadpool(_get_mcp_orchestrator)
    return await run_in_threadpool(orchestrator.plan, body)


@app.post("/schedule", response_model=MCPScheduleResult)
async def schedule_meeting(body: MCPScheduleRequest):
    """Schedule a selected meeting candidate via MCP tools (calendar/memo/map)."""
    orchestrator = await run_in_threadpool(_get_mcp_orchestrator)
    return await run_in_threadpool(
        orchestrator.schedule,
        user_request=body.user_request,
        selected_candidate=body.selected_candidate,
    )


@app.on_event("startup")
async def init_graphiti_client():
    try:
        await _get_graph_client()
        logger.info("Graphiti client initialized.")
    except Exception as exc:
        logger.warning("Graphiti client not initialized at startup: %s", exc)


@app.on_event("shutdown")
async def close_graphiti_client():
    if graph_client:
        await graph_client.close()
    try:
        if graph_agent.graphiti_client:
            await graph_agent.graphiti_client.close()
    except Exception:
        pass


@app.on_event("startup")
def log_configuration():
    if collector.kakao_api_key:
        logger.info("Kakao REST API key is loaded.")
    else:
        logger.warning("Kakao REST API key is missing; API requests will fail.")


# ------------------------------
# Chat router: intent + safe dispatch
# ------------------------------

def _classify_intent(text: str) -> Intent:
    lowered = (text or "").lower()
    suspicious_keywords = ["apoc.", "call dbms", "match (", "return apoc", "system prompt", "ignore previous"]
    if any(kw in lowered for kw in suspicious_keywords):
        return "suspicious"
    place_keywords = ["약속", "만날", "모임", "중간", "회식", "데이트", "식당", "카페", "맛집", "예약", "추천", "주차", "거리", "역", "지하철"]
    if any(kw in lowered for kw in place_keywords):
        return "place_search"
    return "general"


def _general_chat_reply(text: str) -> str:
    """Fallback LLM answer for 일반 대화/기타 질문 (DB나 도구 호출 없이)."""
    try:
        prompt = (
            "다음 사용자의 질문에 대해 간결하게 답변하세요. "
            "도구 호출, DB 조회, 코드 실행 없이 텍스트로만 답변합니다. "
            "명확하지 않으면 짧게 추정하거나 추가 정보 요청을 포함해 주세요.\n"
            f"사용자 질문: {text}"
        )
        return kanana_client.get_response(prompt)
    except Exception as exc:
        logger.exception("General chat LLM failed", extra={"text": text})
        return f"일반 답변을 생성하지 못했습니다: {exc}"


@app.post("/chat", response_model=ChatResponse)
async def chat_router(body: ChatRequest):
    # Agent mode: let the LLM decide the conversational next step and suggestions.
    if body.mode == "agent":
        decision_intent: AgentIntent
        try:
            _ensure_llm_key()
            decision = await run_in_threadpool(_agent_llm_decide, body.message or "", body.history or [])
        except Exception as exc:
            logger.exception("Agent decision failed", extra={"error": str(exc)})
            decision = _agent_fallback(body.message or "")

        decision_intent = decision["intent"]
        return ChatResponse(
            intent=decision_intent,
            reply=decision["reply"],
            suggestions=decision.get("suggestions") or [],
            agent={
                "mode": "llm_agent",
                "conversationId": body.conversationId,
            },
            meta={"steps": ["agent_mode", "llm_decide"], "raw_intent": decision_intent},
        )

    intent = _classify_intent(body.message or "")

    if intent == "suspicious":
        return ChatResponse(
            intent=intent,
            reply="안전하지 않은 요청이라 처리하지 않았습니다.",
            meta={"reason": "suspicious", "steps": ["intent_classify", "blocked_suspicious"]},
        )

    if intent == "place_search":
        try:
            agent_req = ExtractAgentRequest(query=body.message, maxTurns=2)
            result = await run_in_threadpool(run_extraction_agent, agent_req)
            reply = result.llmResult if isinstance(result.llmResult, str) else json.dumps(result.llmResult, ensure_ascii=False)
            meta = {
                "attempts": getattr(result, "attempts", None),
                "extraQueries": getattr(result, "extraQueries", None),
                "sourceCounts": getattr(result, "sourceCounts", None),
                "steps": ["intent_classify", "extraction_agent", "llm_structured_output"],
            }
            return ChatResponse(intent=intent, reply=reply, meta=meta)
        except Exception as exc:
            logger.exception("Place search failed", extra={"query": body.message})
            raise HTTPException(status_code=500, detail=str(exc))

    # general fallback
    reply = await run_in_threadpool(_general_chat_reply, body.message)
    return ChatResponse(intent=intent, reply=reply, meta={"mode": "general", "steps": ["intent_classify", "general_llm"]})


@app.post("/kanana/qa", response_model=KananaQAResponse)
async def kanana_qa(body: KananaQARequest):
    _ensure_llm_key()

    # Scripted demo flow:
    # If the user asks the predefined query, wait 3 seconds then ask for time selection with buttons.
    scripted_query = "이번 주 금요일 강남역 근처에서 4명이서 점심을 먹을거야. 가성비 맛집 추천해줘."
    if (body.user_query or "").strip() == scripted_query:
        await asyncio.sleep(3)
        reply = "더 정확한 정보 제공을 위해서, 몇 시쯤에 가실 예정인가요?"
        suggestions = ["11:00", "12:00", "13:00"]
        updated_memory = list(body.memory or [])
        updated_memory.append(MemoryMessage(role="user", content=body.user_query or ""))
        updated_memory.append(MemoryMessage(role="assistant", content=reply))
        return KananaQAResponse(reply=reply, memory=updated_memory, suggestions=suggestions)

    # Scripted demo follow-up: time selection -> candidates list (clickable UI).
    if (body.user_query or "").strip() in {"11:00", "12:00", "13:00"} and _memory_contains_text(
        body.memory or [], scripted_query
    ):
        candidates: List[MCPMeetingCandidate] = []
        result: MCPOrchestratorResult | None = None

        try:
            assembled_query = (
                f"이번 주 금요일 {body.user_query}에 강남역 근처에서 4명이 점심을 먹을거야. 가성비 맛집 추천해줘."
            )
            orchestrator = await run_in_threadpool(_get_mcp_orchestrator)
            result = await run_in_threadpool(
                orchestrator.plan,
                MCPUserRequest(user_query=assembled_query, user_id=body.user_id, participants=[]),
            )
            candidates = list(result.candidates or [])
        except Exception:
            result = None
            candidates = []

        if not candidates:
            candidates = _build_demo_candidates((body.user_query or "").strip())

        reply = f"총 {len(candidates)}곳을 찾았어요. 아래에서 원하는 곳을 눌러 선택해 주세요."
        updated_memory = list(body.memory or [])
        updated_memory.append(MemoryMessage(role="user", content=body.user_query or ""))
        updated_memory.append(MemoryMessage(role="assistant", content=reply))
        return KananaQAResponse(reply=reply, memory=updated_memory, candidates=candidates, orchestrator=result)

    # Scripted demo follow-up: time selection -> orchestrate candidates list.
    if (body.user_query or "").strip() in {"11:00", "12:00", "13:00"} and _memory_contains_text(
        body.memory or [], scripted_query
    ):
        assembled_query = (
            f"이번 주 금요일 {body.user_query}에 강남역 근처에서 4명이 점심을 먹을거야. 가성비 맛집 추천해줘."
        )
        orchestrator = await run_in_threadpool(_get_mcp_orchestrator)
        result: MCPOrchestratorResult = await run_in_threadpool(
            orchestrator.plan,
            MCPUserRequest(user_query=assembled_query, user_id=body.user_id, participants=[]),
        )
        candidates = list(result.candidates or [])
        reply = f"총 {len(candidates)}곳을 찾았어요. 아래에서 원하는 곳을 눌러 선택해 주세요."
        updated_memory = list(body.memory or [])
        updated_memory.append(MemoryMessage(role="user", content=body.user_query or ""))
        updated_memory.append(MemoryMessage(role="assistant", content=reply))
        return KananaQAResponse(reply=reply, memory=updated_memory, candidates=candidates, orchestrator=result)

    if not _looks_like_meeting_place_query(body.user_query or ""):
        try:
            pivot_prompt = _build_kanana_pivot_prompt(body.user_query or "", body.memory or [])
            reply = await run_in_threadpool(kanana_client.get_response, pivot_prompt, 0.4)
        except Exception:
            reply = _redirect_to_purpose_reply(body.user_query or "")
        updated_memory = list(body.memory or [])
        updated_memory.append(MemoryMessage(role="user", content=body.user_query or ""))
        updated_memory.append(MemoryMessage(role="assistant", content=reply))
        return KananaQAResponse(reply=reply, memory=updated_memory)

    # If we have enough constraints, call the orchestrator and return candidates.
    try:
        readiness_prompt = _build_orchestrate_readiness_prompt(body.user_query or "", body.memory or [])
        readiness_raw = await run_in_threadpool(kanana_client.get_response, readiness_prompt, 0.2)
        readiness = _extract_first_json_object_relaxed(readiness_raw) or {}
    except Exception:
        readiness = {}

    if isinstance(readiness, dict) and readiness.get("ready") is True:
        assembled = readiness.get("assembled_user_query")
        assembled_query = assembled.strip() if isinstance(assembled, str) else (body.user_query or "")
        orchestrator = await run_in_threadpool(_get_mcp_orchestrator)
        result: MCPOrchestratorResult = await run_in_threadpool(
            orchestrator.plan,
            MCPUserRequest(user_query=assembled_query, user_id=body.user_id, participants=[]),
        )

        candidates = list(result.candidates or [])
        reply = f"총 {len(candidates)}곳을 찾았어요. 아래에서 원하는 곳을 눌러 선택해 주세요."

        updated_memory = list(body.memory or [])
        updated_memory.append(MemoryMessage(role="user", content=body.user_query or ""))
        updated_memory.append(MemoryMessage(role="assistant", content=reply))
        return KananaQAResponse(reply=reply, memory=updated_memory, candidates=candidates, orchestrator=result)

    prompt = _build_kanana_qa_prompt(body.user_query or "", body.memory or [])
    reply = await run_in_threadpool(kanana_client.get_response, prompt)

    updated_memory = list(body.memory or [])
    updated_memory.append(MemoryMessage(role="user", content=body.user_query or ""))
    updated_memory.append(MemoryMessage(role="assistant", content=reply or ""))
    return KananaQAResponse(reply=reply or "", memory=updated_memory)


__all__ = ["app"]
