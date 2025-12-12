import os
import json, asyncio
from typing import TypedDict, Annotated, List, Optional, Literal
from pydantic import BaseModel, Field
import logging

from dotenv import load_dotenv
from openai import OpenAI
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.tools.tavily_search import TavilySearchResults
from langgraph.graph import StateGraph, END
from langchain_community.tools import TavilySearchResults

# Graphiti Client (이전 단계에서 설정한 클라이언트라고 가정)
from graphiti_core import Graphiti
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient


load_dotenv(".env.local")
logger = logging.getLogger(__name__)

# ==============================================================================
# 1. 데이터 모델 정의 (Input JSON Mapping)
# ==============================================================================

class Area(BaseModel):
    name: str
    lat: float
    lon: float
    radius_km: float

class DateRange(BaseModel):
    type: str
    start_date: str
    end_date: str

class TimeRange(BaseModel):
    start_time: str
    end_time: Optional[str] = None

class Budget(BaseModel):
    max: int
    currency: str

class MeetingConstraints(BaseModel):
    people_count: int
    area: List[Area]
    meeting_point_strategy: str  # "midpoint" | "fixed"
    departure_points: List[str]
    date_range: DateRange
    time_range: TimeRange
    budget_per_person: Budget
    category_preferences: List[str]
    hard_constraints: List[str]
    soft_constraints: List[str]
    raw_normalized_text: str

class AgentInput(BaseModel):
    constraints: MeetingConstraints
    candidates: List = []
    participants: List = []

# ==============================================================================
# 2. Agent State 정의 (LangGraph)
# ==============================================================================

class AgentState(TypedDict):
    input_data: dict          # 원본 JSON 데이터
    search_query: str         # Graph/Web 검색을 위한 자연어 쿼리
    graph_candidates: List    # GraphRAG 결과
    missing_info: List[str]   # 부족한 정보 리스트 (예: ["주차정보", "최신메뉴"])
    final_candidates: List    # 최종 선별된 후보
    search_attempts: int      # 루프 방지용 카운터

# ==============================================================================
# 3. Nodes (Agent의 사고 과정)
# ==============================================================================

llm = ChatOpenAI(model="kanana-2-30b-a3b-instruct", base_url=os.getenv("KANANA_BASE_URL"), api_key=os.getenv("KANANA_API_KEY"), temperature=0, max_tokens=1024)
web_search_tool = TavilySearchResults(tavily_api_key=os.getenv("TAVILY_API_KEY"), k=3)

llm_config = LLMConfig(
    api_key=os.getenv("KANANA_API_KEY"),
    model="kanana-2-30b-a3b-instruct",
    base_url=os.getenv("KANANA_BASE_URL"),
    max_tokens=1024,
)
graphiti = Graphiti(
    os.environ["NEO4J_URI"],
    os.environ["NEO4J_USERNAME"],
    os.environ["NEO4J_PASSWORD"],
    llm_client=OpenAIGenericClient(config=llm_config, max_tokens=1024),
)

# ------------------------------------------------------------------
# NODE 1: 의도 분석 및 쿼리 확장 (Search Planner)
# ------------------------------------------------------------------
def analyze_request(state: AgentState):
    constraints = state["input_data"]["constraints"]
    
    # 전략 수립 프롬프트
    prompt = ChatPromptTemplate.from_template("""
    당신은 모임 장소 추천 전문가입니다. 
    JSON 제약 조건을 분석하여 Neo4j 지식 그래프에서 검색할 최적의 '자연어 쿼리'와 '필터링 전략'을 수립하세요.
    
    # 입력 데이터:
    - 원문: {raw_text}
    - 인원: {people_count}명
    - 예산: {budget}원
    - 선호: {preferences}
    - 제외: {hard_constraints}
    - 지역: {area_name} (전략: {strategy})
    
    # 수행:
    1. '한식 제외' 같은 부정 조건은 '양식, 일식, 중식, 아시안' 등으로 긍정 키워드로 치환하세요.
    2. 인원 수에 따라 '단체석', '룸' 등의 키워드가 필요한지 판단하세요.
    3. 예산을 고려하여 '가성비', '파인다이닝' 등의 키워드를 추가하세요.
    4. GraphRAG에 보낼 명확한 한 문장의 검색 쿼리를 작성하세요.
    
    출력은 오직 쿼리 문자열만 반환하세요.
    """)
    
    # Midpoint/Fixed 여부에 상관없이 area[0]을 타겟 지역으로 사용
    target_area = constraints["area"][0]["name"]
    
    # [수정됨] 프롬프트와 LLM을 파이프(|)로 연결하여 실행 체인 생성
    chain = prompt | llm
    
    # 체인을 실행하여 실제 응답을 받음
    response = chain.invoke({
        "raw_text": constraints["raw_normalized_text"],
        "people_count": constraints["people_count"],
        "budget": constraints["budget_per_person"]["max"],
        "preferences": ", ".join(constraints["category_preferences"]),
        "hard_constraints": ", ".join(constraints["hard_constraints"]),
        "area_name": target_area,
        "strategy": constraints["meeting_point_strategy"]
    })
    
    # AIMessage 객체의 content 속성 반환
    return {"search_query": response.content}

# ------------------------------------------------------------------
# NODE 2: GraphRAG 수행 (Knowledge Retrieval)
# ------------------------------------------------------------------
async def search_knowledge_graph(state: AgentState):
    query = state["search_query"]
    print(f"🔍 [GraphRAG] 검색 실행: {query}")

    try:
        # [핵심 수정] await를 붙여서 비동기 실행을 기다려야 합니다.
        # graphiti.search()가 실제 데이터를 반환할 때까지 대기
        results = await graphiti.search(query)
        
        # 결과가 객체 리스트라면 직렬화 처리 (필요시)
        serialized_results = []
        if isinstance(results, list):
            for res in results:
                if hasattr(res, "dict"):
                    serialized_results.append(res.model_dump())
                elif hasattr(res, "__dict__"):
                    serialized_results.append(res.__dict__)
                else:
                    serialized_results.append(str(res))
        else:
            serialized_results = str(results)

        # 정상적으로 키를 반환
        return {"graph_candidates": serialized_results}

    except Exception as e:
        print(f"❌ Graph Search Error: {e}")
        # 에러가 나더라도 다음 단계가 죽지 않도록 빈 리스트 반환
        return {"graph_candidates": []}
    
    # [Mockup Result] Graphiti가 반환했다고 가정하는 데이터
    # 실제로는 Neo4j에서 spatial distance calculation도 포함되어야 함
    # mock_results = [
    #     {"name": "더플레이스", "category": "이탈리안", "menu": "파스타, 스테이크", "price": "2만원대", "atmosphere": "모던함"},
    #     {"name": "갓포아키", "category": "일식", "menu": "사시미", "price": "5만원대", "atmosphere": "조용함"}, 
    # ]
    
    # return {"graph_candidates": mock_results}

# ------------------------------------------------------------------
# NODE 3: 결과 평가 및 결핍 분석 (The Intelligent "Gap Analysis")
# ------------------------------------------------------------------
def evaluate_results(state: AgentState):
    """
    Graph 결과가 제약조건을 만족하는지, 추가 정보가 필요한지 판단
    """
    constraints = state["input_data"]["constraints"]
    candidates = state["graph_candidates"]
    
    eval_prompt = ChatPromptTemplate.from_template("""
    사용자의 제약 조건과 Graph 검색 결과를 비교하여 부족한 점을 찾으세요.

    # 제약 조건:
    {constraints}

    # 검색된 후보:
    {candidates}

    # 판단 기준:
    1. 예산({budget})을 초과하는 곳은 제외해야 함.
    2. 필수 정보(주차, 영업시간 등)가 누락되었는지 확인.
    3. '한식 제외' 등의 Hard Constraint가 지켜졌는지 확인.
    4. 후보가 부족하거나(2개 미만), 정보가 불확실하면 'WebSearchNeeded'라고 판단.

    # 출력 형식(JSON):
    {{
        "valid_candidates": ["이름1", "이름2"],
        "missing_info_needs_search": ["이름1의 주차정보", "이름2의 현재 웨이팅상태"] (없으면 빈 리스트)
    }}
    """)
    
    # LLM 판단
    chain = eval_prompt | llm 
    response = chain.invoke({
        "constraints": json.dumps(constraints, ensure_ascii=False),
        "candidates": str(candidates),
        "budget": constraints["budget_per_person"]["max"]
    })
    
    try:
        # JSON Parsing (실제론 OutputParser 사용 권장)
        eval_result = json.loads(response.content.replace("```json", "").replace("```", ""))
        
        return {
            "final_candidates": [c for c in candidates if c['name'] in eval_result['valid_candidates']],
            "missing_info": eval_result['missing_info_needs_search']
        }
    except:
        # 파싱 에러 시 안전하게 처리
        return {"missing_info": [], "final_candidates": candidates}

# ------------------------------------------------------------------
# NODE 4: 외부 정보 검색 (Web Search / MCP)
# ------------------------------------------------------------------
def fetch_missing_info(state: AgentState):
    missing_items = state["missing_info"]
    current_candidates = state["final_candidates"]
    
    print(f"🌐 [WebSearch] 부족한 정보 보강: {missing_items}")
    
    enriched_candidates = []
    
    # 각 결핍 정보에 대해 검색 수행 (병렬 처리 권장)
    for query in missing_items:
        search_res = web_search_tool.invoke(query)
        # 검색 결과를 해당 후보 데이터에 병합하는 로직 (간소화됨)
        # 실제론 어떤 후보에 대한 정보인지 매핑해야 함
    
    # 여기서는 데모용으로 기존 후보에 태그만 추가
    for cand in current_candidates:
        cand['enriched_source'] = 'Web + Graph'
        enriched_candidates.append(cand)
        
    return {
        "final_candidates": enriched_candidates,
        "missing_info": [] # 결핍 해소됨
    }

# ==============================================================================
# 4. Graph Construction (Workflow 정의)
# ==============================================================================

def route_decision(state: AgentState) -> Literal["fetch_missing_info", "end"]:
    if state["missing_info"] and len(state["missing_info"]) > 0:
        return "fetch_missing_info"
    return "end"

workflow = StateGraph(AgentState)

# 노드 추가
workflow.add_node("analyze", analyze_request)
workflow.add_node("graph_rag", search_knowledge_graph)
workflow.add_node("evaluate", evaluate_results)
workflow.add_node("web_search", fetch_missing_info)

# 엣지 연결
workflow.set_entry_point("analyze")
workflow.add_edge("analyze", "graph_rag")
workflow.add_edge("graph_rag", "evaluate")

# 조건부 엣지 (결핍 정보가 있으면 웹 검색, 없으면 종료)
workflow.add_conditional_edges(
    "evaluate",
    route_decision,
    {
        "fetch_missing_info": "web_search",
        "end": END
    }
)
workflow.add_edge("web_search", END)

# 컴파일
app = workflow.compile()

# ==============================================================================
# 5. 실행 예시
# ==============================================================================

async def main():
    # Case 1: Midpoint (Area 정보가 계산되어 들어옴)
    input_json = {
        "constraints": {
        "people_count": 3,
        "area": [{
            "name": "서울특별시 용산구 용산동6가",
            "lat": "37.526188",
            "lon": "126.981898",
            "radius_km": 5
        }],
        "meeting_point_strategy": "midpoint",
        "departure_points": ["건대입구", "홍대입구", "서울대입구"],
        "date_range": {"type": "single_day", "start_date": "2025-12-10", "end_date": "2025-12-10"},
        "time_range": {"start_time": "18:00"},
        "budget_per_person": {"max": 40000, "currency": "KRW"},
        "category_preferences": ["한식 제외"],
        "hard_constraints": [],
        "soft_constraints": [],
        "raw_normalized_text": "..."
        }
    }

    # [핵심 수정] invoke -> ainvoke (비동기 호출)
    # await 키워드 필수
    result = await app.ainvoke({"input_data": input_json})
    
    print("\n✅ Final Result:")
    print(result["final_candidates"])
    
    await graphiti.close()
        
if __name__ == "__main__":
    if os.name == "nt" or sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())