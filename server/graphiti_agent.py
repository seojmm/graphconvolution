import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from dotenv import load_dotenv
from tqdm.asyncio import tqdm

from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType

# 모델 및 수집기 임포트 (기존 유지)
from models import (
    PlaceEntity, PhoneEntity, ParkingEntity, BreaktimeEntity, 
    OpeningHoursEntity, ClosedDaysEntity, MenuEntity, NoteEntity,
    HasPhone, HasParking, HasBreaktime, HasOpeningHours, 
    HasClosedDays, HasMenu, HasNote
)
from kakao_data_collector import KakaoDataCollector

# [NEW] 새로 만든 서비스 임포트
from extraction_service import ExtractionService

# 로깅 설정 (기존 유지)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Custom schema reused from graphiti_agent.py
entity_types = {
    "Place": PlaceEntity,
    "Phone": PhoneEntity,
    "Parking": ParkingEntity,
    "Breaktime": BreaktimeEntity,
    "OpeningHours": OpeningHoursEntity,
    "ClosedDays": ClosedDaysEntity,
    "Menu": MenuEntity,
    "Note": NoteEntity,
}

edge_types = {
    "HAS_PHONE": HasPhone,
    "HAS_PARKING": HasParking,
    "HAS_BREAKTIME": HasBreaktime,
    "HAS_OPENING_HOURS": HasOpeningHours,
    "HAS_CLOSED_DAYS": HasClosedDays,
    "HAS_MENU": HasMenu,
    "HAS_NOTE": HasNote,
}

edge_type_map = {
    ("Place", "Phone"): ["HAS_PHONE"],
    ("Place", "Parking"): ["HAS_PARKING"],
    ("Place", "Breaktime"): ["HAS_BREAKTIME"],
    ("Place", "OpeningHours"): ["HAS_OPENING_HOURS"],
    ("Place", "ClosedDays"): ["HAS_CLOSED_DAYS"],
    ("Place", "Menu"): ["HAS_MENU"],
    ("Place", "Note"): ["HAS_NOTE"],
}

# 환경 변수 로드
load_dotenv(dotenv_path='.env.local')

# 전역 클라이언트 변수 (Tool에서 접근하기 위함)
graphiti_client: Graphiti = None

# 전역 서비스 인스턴스
extractor_service = ExtractionService()


# -------------------------------------------------------------------------
# Kakao -> Graphiti 적재 (from graphiti_agent.py)
# -------------------------------------------------------------------------
def fetch_all_seoul(limit_per_category: Optional[int] = None) -> List[Dict[str, Any]]:
    collector = KakaoDataCollector()
    districts = collector.regions.get("seoul", {}).get("districts", [])
    categories = list(collector.category_mapping.keys())
    all_places: List[Dict[str, Any]] = []

    for district in districts:
        district_raw: List[Dict[str, Any]] = []
        for category in categories:
            chunk = collector.collect_kakao_data("seoul", district, category)
            district_raw.extend(chunk if limit_per_category is None else chunk[:limit_per_category])
        # unique = collector._deduplicate_restaurants(district_raw)
        all_places.extend(district_raw)
        logger.info("Collected district", extra={"district": district, "count": len(district_raw)})

    logger.info("Collected all Seoul districts", extra={"total": len(all_places)})
    return all_places


def _rename_for_graph(place: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(place)
    payload["place_name"] = payload.pop("placeName", "")
    payload["road_address"] = payload.pop("roadAddressName", "")
    payload["sub_category"] = payload.pop("subCategory", "")
    payload["opening_hours"] = payload.pop("openingHours", "")
    payload["is_open"] = payload.pop("isOpen", None)
    payload["is_recommended"] = payload.pop("isRecommended", False)
    return payload


async def process_single_place(sem: asyncio.Semaphore, graph: Graphiti, place: Dict[str, Any], description: str):
    """
    세마포어(Semaphore)를 사용하여 동시 실행 수를 제어하며 단일 장소를 처리하는 함수
    """
    async with sem:
        # 1. 데이터 강화 (Enrichment) - API 서버 호출 없이 직접 수행
        query_text = f"{place.get('name', '')} {place.get('address', '')}".strip()
        if query_text:
            try:
                # 직접 서비스 호출 (HTTP 오버헤드 제거)
                extracted = await extractor_service.extract_info(query_text)
                if extracted:
                    place.update(extracted)
            except Exception as e:
                logger.warning(f"Failed to enrich {place.get('name')}: {e}")

        # 2. 데이터 변환 (Transformation) - 기존 로직 재사용
        # _rename_for_graph 함수는 내부에 그대로 두거나 import 해서 사용
        payload = _rename_for_graph(place)

        # 3. 데이터 적재 (Load)
        try:
            await graph.add_episode(
                name=payload.get("place_name") or "place",
                episode_body=json.dumps(payload, ensure_ascii=False),
                source=EpisodeType.json,
                source_description=description,
                reference_time=datetime.now(timezone.utc),
                entity_types=entity_types,
                edge_types=edge_types,
                edge_type_map=edge_type_map,
            )
        except Exception as e:
            logger.error(f"Graph insert failed for {place.get('place_name')}: {e}")


async def ingest_kakao_places(limit_per_category: Optional[int] = None, description: str = "Detail Information of Places") -> None:
    ensure_env()
    if graphiti_client is None:
        raise RuntimeError("Graphiti client is not initialized; call init_client() first.")

    places = fetch_all_seoul(limit_per_category=limit_per_category)
    count = 0
    fastapi_base = os.getenv("FASTAPI_BASE_URL")
    if not fastapi_base:
        raise RuntimeError("FASTAPI_BASE_URL is required to call /extract for enrichment.")
    for place in places:
        query_text = f"{place.get('placeName', '')} {place.get('addressName', '')}".strip()
        print("Querying extract for:", query_text)
        if not query_text:
            logger.warning("Skip extract: empty query_text", extra={"place": place})
            continue
        extracted = _fetch_extract_info(fastapi_base, query_text)
        if extracted:
            place.update(extracted)

        payload = _rename_for_graph(place)
        print(f"payload: {payload}")
        await graphiti_client.add_episode(
            name=payload.get("place_name"),
            episode_body=json.dumps(payload, ensure_ascii=False),
            source=EpisodeType.json,
            source_description=description,
            reference_time=datetime.now(timezone.utc),
            # entity_types=entity_types,
            # edge_types=edge_types,
            # edge_type_map=edge_type_map,
        )
        count += 1
    logger.info(f"Seeded places: {count}", extra={"count": count})

# -------------------------------------------------------------------------
# 2. Tools 정의
# -------------------------------------------------------------------------
@tool
async def save_episode(name: str, content: str, episode_type: str = "text", description: str = "User conversation episode") -> str:
    """사용자가 제공한 정보를 저장합니다."""
    episode_type_map = {'text': EpisodeType.text, 'json': EpisodeType.json, 'message': EpisodeType.message}
    ep_type = episode_type_map.get(episode_type.lower(), EpisodeType.text)

    await graphiti_client.add_episode(
        name=name,
        episode_body=content,
        source=ep_type,
        source_description=description,
        reference_time=datetime.now(timezone.utc),
    )
    return f"에피소드 '{name}'이 성공적으로 저장되었습니다."

@tool
async def get_memory(query: str) -> str:
    """사용자와의 대화 기록이나 저장된 정보를 검색합니다."""
    edge_results = await graphiti_client.search(query, num_results=5)
    return edges_to_facts_string(edge_results)

# -------------------------------------------------------------------------
# 3. 기능별 함수
# -------------------------------------------------------------------------

async def init_client():
    """Graphiti 클라이언트 초기화 및 인덱스 빌드"""
    global graphiti_client
    uri = os.environ.get('NEO4J_URI')
    user = os.environ.get('NEO4J_USERNAME')
    pwd = os.environ.get('NEO4J_PASSWORD')
    
    if not uri or not user or not pwd:
        raise ValueError("NEO4J 환경 변수가 설정되지 않았습니다.")
        
    graphiti_client = Graphiti(uri, user, pwd)
    await graphiti_client.build_indices_and_constraints()
    print(">>> Graphiti Client Initialized & Indices Built")


async def run_search_demo(query: str = "OpenAI의 정보를 알려주세요."):
    """검색 기능 테스트 (기본, 중심 노드, RRF)"""
    print(f"\n>>> Searching for: '{query}'")
    
    # 1. 기본 검색
    results = await graphiti_client.search(query)
    print(f"[Basic Search] Found {len(results)} edges.")
    
    if not results:
        return

    # 2. 중심 노드 기반 재정렬
    center_node_uuid = results[0].source_node_uuid
    print(f"\n>>> Reranking with center node: {center_node_uuid}")
    reranked = await graphiti_client.search(query, center_node_uuid=center_node_uuid)
    for r in reranked[:2]:
        print(f" - Fact: {r.fact}")

    # 3. 노드 검색 (RRF)
    print("\n>>> Node Search (RRF) for 'gpt-5'")
    node_cfg = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
    node_cfg.limit = 3
    node_results = await graphiti_client._search(query='gpt-5', config=node_cfg)
    for node in node_results.nodes:
        print(f" - Node: {node.name} (UUID: {node.uuid})")

# -------------------------------------------------------------------------
# 4. Agent 정의 및 실행
# -------------------------------------------------------------------------

# State 정의
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    user_name: str
    user_node_uuid: str

async def run_custom_agent_demo(user_query: str):
    """LangGraph를 이용한 커스텀 에이전트 실행"""
    print(f"\n>>> Running Custom Agent with query: {user_query}")
    
    llm = ChatOpenAI(model="gpt-4o", temperature=0)
    tools = [save_episode, get_memory]
    llm_with_tools = llm.bind_tools(tools)

    # 챗봇 노드
    async def chatbot(state: AgentState):
        facts_string = None
        
        # 문맥 검색
        if len(state['messages']) > 0:
            last_msg = state['messages'][-1]
            q = f"{'AI' if isinstance(last_msg, AIMessage) else state['user_name']}: {last_msg.content}"
            
            # 사용자 노드 UUID가 있다면 중심 노드로 활용
            center_uuid = state.get("user_node_uuid")
            # UUID가 빈 문자열이면 None으로 처리
            if not center_uuid: 
                center_uuid = None
                
            edge_results = await graphiti_client.search(q, center_node_uuid=center_uuid, num_results=5)
            facts_string = edges_to_facts_string(edge_results)

        system_msg = SystemMessage(content=f"""
        당신은 최신 정보를 저장하고 이를 기반으로 답변하는 지능형 에이전트입니다.
        사용자 관련 정보 및 대화 기록:
        {facts_string}
        """)
        
        messages = [system_msg] + state['messages']
        response = await llm_with_tools.ainvoke(messages)
        
        # 도구 호출이 아닐 경우 대화 내용 저장
        if not response.tool_calls:
            asyncio.create_task(
                graphiti_client.add_episode(
                    name='Chatbot Response',
                    episode_body=f"{state['user_name']}: {state['messages'][-1].content}\nAI: {response.content}",
                    source=EpisodeType.message,
                    reference_time=datetime.now(timezone.utc),
                    source_description='Chatbot',
                )
            )
        return {'messages': [response]}

    # 조건부 엣지
    def should_continue(state, config):
        if not state['messages'][-1].tool_calls:
            return 'end'
        return 'continue'

    # 그래프 빌드
    workflow = StateGraph(AgentState)
    workflow.add_node('agent', chatbot)
    workflow.add_node('tools', ToolNode(tools))

    workflow.add_edge(START, 'agent')
    workflow.add_conditional_edges('agent', should_continue, {'continue': 'tools', 'end': END})
    workflow.add_edge('tools', 'agent')

    app = workflow.compile(checkpointer=MemorySaver())

    # 실행
    config = {'configurable': {'thread_id': uuid.uuid4().hex}}
    inputs = {
        'messages': [{'role': 'user', 'content': user_query}],
        'user_name': 'User',
        'user_node_uuid': '' # 필요 시 사용자 노드 검색 후 ID 주입
    }

    async for event in app.astream(inputs, config=config):
        for key, value in event.items():
            if 'messages' in value:
                last_msg = value['messages'][-1]
                print(f"[{key}] {last_msg.content}")

# -------------------------------------------------------------------------
# Main Execution
# -------------------------------------------------------------------------
async def main():
    # 초기화 (필수)
    await init_client()

    # Kakao Graphiti 적재 (graphiti_agent 역할, 필요시 주석 해제)
    await ingest_kakao_places()

    # 검색 기능 테스트 (필요시 주석 해제)
    # await run_search_demo("몽중헌 청담점은 주차 가능한가요?")

    # 에이전트 실행 (필요시 주석 해제)
    # await run_custom_agent_demo("2025년 12월 10일 저녁 6시에 회식할 건데, 총 3명에서 만날 예정이고 각자 건대입구역, 홍대입구역, 서울대입구역에서 출발할 거야. 회식비는 총 12만원 내외로 사용 가능하고, 한식은 제외해줘. 식당 추천해줄래?")

    # 종료 시 클라이언트 정리
    await graphiti_client.close()

if __name__ == "__main__":
    asyncio.run(main())
