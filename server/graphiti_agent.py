# ### ⚙️ 환경 설정
# `pip install -qU langgraph langchain-core langchain-openai graphiti-core`
# `pip install -r requirements.txt`
import asyncio
import json
import logging
from logging import INFO
import os
from datetime import datetime, timezone, timedelta
import uuid
from typing import Annotated
from typing_extensions import TypedDict

from dotenv import load_dotenv
import requests
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.prebuilt import ToolNode, create_react_agent

from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType
from graphiti_core.search.search_config_recipes import NODE_HYBRID_SEARCH_RRF
from kakao_data_collector import KakaoDataCollector

logging.basicConfig(
    level=INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

load_dotenv(".env.local")

# Windows asyncio SSL/proactor 이슈 회피
if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

neo4j_uri = os.environ.get('NEO4J_URI')
neo4j_user = os.environ.get('NEO4J_USER')
neo4j_password = os.environ.get('NEO4J_PASSWORD')

if not neo4j_uri or not neo4j_user or not neo4j_password:
    raise ValueError('NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD must be set')

# ## 🔧Graphiti 사용하기
graphiti = Graphiti(neo4j_uri, neo4j_user, neo4j_password)


# Helper to format edge results

def edges_to_facts_string(edges):
    """
    검색 결과를 문자열로 변환하여 출력.
    """
    if not edges:
        return "관련 정보를 찾을 수 없습니다."

    current_time = datetime.now(timezone.utc)

    def is_expired(edge):
        if not (hasattr(edge, 'invalid_at') and edge.invalid_at):
            return False
        try:
            invalid_time = edge.invalid_at
            if isinstance(invalid_time, str):
                invalid_time = datetime.fromisoformat(invalid_time.replace('Z', '+00:00'))
            if invalid_time.tzinfo is None:
                invalid_time = invalid_time.replace(tzinfo=timezone.utc)
            return current_time > invalid_time
        except Exception:
            return False

    def get_fact_content(edge):
        return edge.fact if hasattr(edge, 'fact') and edge.fact else str(edge)

    valid_facts = [get_fact_content(edge) for edge in edges if not is_expired(edge)]
    expired_count = len(edges) - len(valid_facts)

    if not valid_facts:
        return (
            f"관련 정보가 없지만 모두 만료되었습니다 (만료 정보 {expired_count}개)"
            if expired_count
            else "관련 정보를 찾을 수 없습니다."
        )

    result = "=== 현재 유효한 정보 ===\n" + "\n".join(valid_facts)
    if expired_count:
        result += f"\n\n[만료된 정보: {expired_count}개]"
    return result


@tool
async def save_episode(
    name: str,
    content: str,
    episode_type: str = "text",
    description: str = "User conversation episode",
) -> str:
    """
    사용자 정보를 그래프에 저장.
    """
    try:
        episode_type_map = {
            'text': EpisodeType.text,
            'json': EpisodeType.json,
            'message': EpisodeType.message,
        }
        ep_type = episode_type_map.get(episode_type.lower(), EpisodeType.text)

        await graphiti.add_episode(
            name=name,
            episode_body=content,
            source=ep_type,
            source_description=description,
            reference_time=datetime.now(timezone.utc),
        )

        return f"에피소드 '{name}'가 저장되었습니다. (type={episode_type})"

    except Exception as e:
        return f"에피소드 저장 중 오류: {str(e)}"


@tool
async def get_memory(query: str) -> str:
    """
    그래프에서 최근 관련 정보를 검색합니다.
    """
    try:
        edge_results = await graphiti.search(query, num_results=5)
        return edges_to_facts_string(edge_results)
    except Exception as e:
        return f"정보 검색 중 오류 발생: {str(e)}"


tools = [save_episode, get_memory]
tool_node = ToolNode(tools)

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
llm_with_tools = llm.bind_tools(tools)


def ensure_kakao_key():
    if not os.environ.get("KAKAO_REST_API_KEY"):
        raise ValueError("KAKAO_REST_API_KEY is not configured.")


async def chatbot(state):
    # 기본 정보 검색
    facts_string = None
    if len(state['messages']) > 0:
        last_message = state['messages'][-1]
        graphiti_query = f'{"AI" if isinstance(last_message, AIMessage) else state["user_name"]}: {last_message.content}'
        edge_results = await graphiti.search(
            graphiti_query,
            center_node_uuid=state["user_node_uuid"],
            num_results=5,
        )
        facts_string = edges_to_facts_string(edge_results)

    system_message = SystemMessage(
        content=f"""당신은 최신 정보를 기반으로 응답하는 에이전트입니다.
사용자가 제공한 정보 외 추가 정보는 get_memory로 검색해 활용하세요.

보유 정보:
{facts_string}
"""
    )

    messages = [system_message] + state['messages']
    response = await llm_with_tools.ainvoke(messages)

    # 메시지 저장은 비동기로 처리
    if not response.tool_calls:
        asyncio.create_task(
            graphiti.add_episode(
                name='Chatbot Response',
                episode_body=f"{state['user_name']}: {state['messages'][0]}\nAI: {response.content}",
                source=EpisodeType.message,
                reference_time=datetime.now(timezone.utc),
                source_description='Chatbot',
            )
        )

    return {'messages': [response]}


async def should_continue(state, config):
    messages = state['messages']
    last_message = messages[-1]
    return 'continue' if last_message.tool_calls else 'end'


def build_graph():
    graph_builder = StateGraph({'messages': Annotated[list, add_messages], 'user_name': str, 'user_node_uuid': str})
    graph_builder.add_node('agent', chatbot)
    graph_builder.add_node('tools', tool_node)
    graph_builder.add_edge(START, 'agent')
    graph_builder.add_conditional_edges('agent', should_continue, {'continue': 'tools', 'end': END})
    graph_builder.add_edge('tools', 'agent')
    memory = MemorySaver()
    return graph_builder.compile(checkpointer=memory)


def seed_history():
    return [
        {
            "messages": """
                nayeon: 엄마 근데 소미는 뭐라 그래. 그게 누구야?
                AI: 네 소미는 누구길래 궁금해하나요?
            """
        },
        {
            "messages": """
                nayeon: 어제 설계서가 마음에 안 든다던데, 다시 요청해야 될까?
                AI: 프로젝트 설계서라면 수정 요청 전에 팀원들과 우선 검토해보는 게 좋을 듯해요.
            """
        },
    ]


def fetch_places_for_graph(region: str = "seoul", district: str = "용산구", category: str = "일식"):
    """
    Kakao Local API를 통해 /places와 동일한 방식으로 장소 데이터를 가져온다.
    """
    ensure_kakao_key()
    collector = KakaoDataCollector()
    raw = collector.collect_kakao_data(region, district, category)
    unique = collector._deduplicate_restaurants(raw)
    enriched = [collector._enrich_restaurant_data(item) for item in unique]
    logger.info(
        "Collected places",
        extra={"count": len(enriched), "region": region, "district": district, "category": category},
    )
    return enriched


async def seed_places_into_graphiti(places: list, description: str = "kakao place"):
    """
    장소 정보를 Graphiti에 EpisodeType.json 형태로 적재.
    """
    for place in places:
        await graphiti.add_episode(
            name=place.get("name", "place"),
            episode_body=json.dumps(place, ensure_ascii=False),
            source=EpisodeType.json,
            source_description=description,
            reference_time=datetime.now(timezone.utc),
        )
    logger.info("Seeded places into graphiti", extra={"count": len(places)})


async def main():
    try:
        # 인덱스/제약 생성
        await graphiti.build_indices_and_constraints()

        # Kakao places -> Graphiti (example: Seoul, 용산구, 일식)
        places = fetch_places_for_graph(region="seoul", district="용산구", category="일식")
        top_places = places[:10]
        await seed_places_into_graphiti(top_places, description="kakao places seoul/yongsan/일식 (top 10)")

        # Graph에 Kakao 장소 데이터만 적재 (서울/용산구/일식 예시)
        logger.info("Seeding completed", extra={"places": len(top_places)})
    finally:
        try:
            await graphiti.close()
        except Exception:
            logger.exception("Failed to close graphiti")


if __name__ == "__main__":
    asyncio.run(main())


