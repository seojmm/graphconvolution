# main.py

import os
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

# Domain 모델
from MCPs.App.Domain.model import (
    UserRequest,
    OrchestratorResult,
    ScheduleRequest,
    ScheduleResult,
)

# Agents
from MCPs.App.agents.constraint_extraction import ConstraintExtractionAgent
from MCPs.App.agents.knowledge_agent import KnowledgeAgent
from MCPs.App.agents.verification_agent import VerificationAgent
from MCPs.App.agents.action_agent import ActionAgent

# Ports (인프라 인터페이스 구현체)
from MCPs.App.ports.meeting_repository import InMemoryMeetingRepository  # 나중에 Neo4jMeetingRepository로 교체
from MCPs.App.ports.eta_service import KakaoMapEtaService                  
from MCPs.App.ports.calender_gateway import KakaoCalenderGateway
from MCPs.App.ports.midpoint_service import KakaoMapMidpointService, DummyMidpointService
 
from MCPs.kakao_mcp import PlayMCPClient
# Orchestrator
from MCPs.App.orchestrator.orchestrator import Orchestrator


load_dotenv()  # load KANANA_BASE_URL/KANANA_API_KEY from .env in project root
# 기본 로깅 레벨 설정 (INFO 이상 출력)
logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작 시 PlayMCP 세션 초기화."""
    try:
        talk_calender_client.initialize(client_name="graphconvolution", client_version="0.1.0")
        logging.info("PlayMCP initialize completed.")
    except Exception as exc:
        logging.warning("PlayMCP initialize failed: %s", exc)
    yield
    # 종료 시 특별한 정리 작업 없음


app = FastAPI(
    title="Meeting Multi-Agent Orchestrator",
    version="0.1.0",
    description="자연어 회식/모임 요청을 받아 후보 장소/시간을 추천하는 에이전트 오케스트레이션 서버",
    lifespan=lifespan,
)

# ------------------------------------------------------
# 1) 각 에이전트/포트 인스턴스 생성 (wiring)
# ------------------------------------------------------

# 1-1. 제약 추출 에이전트 (지금은 mock, 나중에 Kanana LLM 모드 추가)
constraint_agent = ConstraintExtractionAgent(mode="llm")

# 1-2. KnowledgeAgent가 사용할 MeetingRepository (지금은 InMemory 더미)
meeting_repo = InMemoryMeetingRepository()
knowledge_agent = KnowledgeAgent(meeting_repository=meeting_repo)

# 1-3. VerificationAgent가 사용할 EtaService (지금은 Dummy, 나중에 KakaoMapEtaService)
eta_service = KakaoMapEtaService()
verification_agent = VerificationAgent(eta_service=eta_service)

# 1-4. ActionAgent가 사용할 CalenderGateway (PlayMCP 톡캘린더 MCP 클라이언트 사용)
play_mcp_toolbox_url = (
    os.getenv("PLAY_MCP_ENDPOINT")
    or os.getenv("PLAY_MCP_TOOLBOX_URL")
    or "https://playmcp.kakao.com/mcp"
)

talk_calender_client = PlayMCPClient(
    base_url=play_mcp_toolbox_url or "",
)
calender_gateway = KakaoCalenderGateway(talk_calender_client=talk_calender_client)
action_agent = ActionAgent(calender_gateway=calender_gateway)

# 1-5. MidpointService (중간지점 계산용 MCP 자리)
# 환경변수에 카카오 REST 키가 있으면 실제 호출, 아니면 더미 사용
kakao_rest_key = os.getenv("KAKAO_REST_API_KEY")
if kakao_rest_key:
    midpoint_service = KakaoMapMidpointService(rest_api_key=kakao_rest_key)
else:
    midpoint_service = DummyMidpointService()

# 1-6. Orchestrator 조립
orchestrator = Orchestrator(
    constraint_agent=constraint_agent,
    knowledge_agent=knowledge_agent,
    verification_agent=verification_agent,
    action_agent=action_agent,
    midpoint_service=midpoint_service,
)


# ------------------------------------------------------
# 2) 엔드포인트 정의
# ------------------------------------------------------

@app.post("/orchestrate", response_model=OrchestratorResult)
def orchestrate(request: UserRequest):
    """
    자연어 쿼리를 받아서:
    1) 제약 추출
    2) 후보 생성
    3) 형평성/품질 평가
    까지 한 번에 수행하고, 후보 리스트를 반환.
    """
    return orchestrator.plan(request)


@app.post("/schedule", response_model=ScheduleResult)
def schedule(body: ScheduleRequest):
    """
    클라이언트가 후보 중 하나를 선택했을 때 호출:
    - 선택된 후보로 실제(또는 mock) 일정 생성.
    """
    return orchestrator.schedule(
        user_request=body.user_request,
        selected_candidate=body.selected_candidate,
    )
