# server/graph_rag.py

"""
Graphiti + LLM 을 이용한 GraphRAG 파이프라인.

기능:
- Graphiti 지식 그래프에서 Place 관련 노드/사실을 하이브리드 검색으로 가져온 뒤
- LLM(Kanana)을 사용해서 "두 지역이 만나기 좋은 장소"를 추천하는 로직.

실행 예:
    uv run python server/graph_rag.py
"""

import asyncio
import json
import logging
import os
from typing import List, Optional

from dotenv import load_dotenv

from graphiti_core import Graphiti
from graphiti_core.edges import EntityEdge
from graphiti_core.nodes import EntityNode
from graphiti_core.search.search_config_recipes import NODE_HYBRID_SEARCH_RRF
from graphiti_core.search.search_filters import SearchFilters  # 검색 필터 

from llm_response import LLMResponse

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Graphiti 연결 유틸
# ----------------------------------------------------------------------


async def create_graphiti_from_env() -> Graphiti:
    """
    .env.local 에서 NEO4J / Graphiti 환경변수를 읽어 Graphiti 인스턴스를 만든다.
    """
    load_dotenv(".env.local")

    neo4j_uri = os.environ["NEO4J_URI"]
    neo4j_user = os.environ["NEO4J_USER"]
    neo4j_password = os.environ["NEO4J_PASSWORD"]

    graph = Graphiti(neo4j_uri, neo4j_user, neo4j_password)

    # 인덱스/제약조건은 여러번 호출해도 idempotent 하게 처리됨. 
    await graph.build_indices_and_constraints()
    return graph


# ----------------------------------------------------------------------
# GraphRAG 핵심 클래스
# ----------------------------------------------------------------------


class PlaceMeetingGraphRAG:
    """
    - Graphiti 에서 Place 노드를 검색하고
    - LLM 으로 "두 지역이 만나기 좋은 장소"를 추론하는 GraphRAG 파이프라인.
    """

    def __init__(self, graphiti: Graphiti, llm: Optional[LLMResponse] = None):
        self.graphiti = graphiti
        self.llm = llm or LLMResponse()

    # ----- 1단계: 그래프 검색 -----

    async def _search_place_nodes(
        self,
        query: str,
        limit: int = 30,
    ):
        """
        Graphiti의 하이브리드 검색으로 Place 노드 위주로 서브그래프를 가져온다.

        - Node Hybrid Search 를 사용해서 엔티티(노드)를 검색 
        - SearchFilters(node_labels=["Place"]) 로 Place 엔티티에만 집중
        """
        # 검색 전략: NODE_HYBRID_SEARCH_RRF 레시피를 베이스로 사용 
        search_config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
        search_config.limit = limit

        search_filter = SearchFilters(
            node_labels=["Place"],  # 우리 도메인의 Place 엔티티만 가져오기
        )

        results = await self.graphiti.search(
            query=query,
            config=search_config,
            search_filter=search_filter,
        )
        return results

    # ----- 2단계: EntityNode → 우리 도메인 dict 로 정리 -----

    @staticmethod
    def _node_to_place_dict(node: EntityNode) -> dict:
        """
        Graphiti EntityNode 를 우리가 쓰기 좋은 dict 로 변환.

        - node.name, node.summary
        - node.attributes 안에 우리가 Place 에 넣었던 속성들(address, district, category 등)이 들어있다. 
        """
        attrs = node.attributes or {}

        def _get(*keys, default=None):
            for k in keys:
                if k in attrs:
                    return attrs[k]
            return default

        return {
            "uuid": node.uuid,
            "name": node.name,
            "summary": (node.summary or "").strip(),
            "address": _get("address"),
            "roadAddress": _get("roadAddress", "road_address"),
            "region": _get("region"),
            "district": _get("district"),
            "category": _get("category"),
            "subCategory": _get("subCategory", "sub_category"),
            "latitude": _get("latitude"),
            "longitude": _get("longitude"),
            "rating": _get("rating"),
            "isRecommended": _get("isRecommended", "is_recommended"),
            "tags": _get("tags", default=[]),
        }

    # ----- 3단계: LLM 프롬프트 구성 & 호출 -----

    async def recommend_meeting_places(
        self,
        region_a: str,
        district_a: str,
        region_b: str,
        district_b: str,
        category: str = "카페",
        limit: int = 3,
    ) -> List[dict]:
        """
        두 지역(행정구역) 사람들끼리 만나기 좋은 Place 를 추천한다.

        결과는 LLM이 반환한 JSON(list[dict])을 그대로 반환.
        """

        user_question = (
            f"{region_a} {district_a}에 사는 사람과 "
            f"{region_b} {district_b}에 사는 사람이 "
            f"만나기 좋은 {category}를 추천해줘. "
            "두 사람 모두에게 이동 시간이 공평하도록 중간 지점을 우선 고려해."
        )

        # 1) 그래프에서 Place 노드 검색
        results = await self._search_place_nodes(user_question, limit=limit * 4)

        # SearchResults.nodes 안에는 EntityNode 들이 들어있음 
        place_nodes: List[EntityNode] = [
            n for n in results.nodes
            if "Place" in (n.labels or [])
        ]

        if not place_nodes:
            logger.warning("Graphiti search returned no Place nodes", extra={"query": user_question})
            return []

        candidate_places = [
            self._node_to_place_dict(node)
            for node in place_nodes
        ]

        # LLM에 넘길 컨텍스트 (JSON 배열 그대로 문자열로)
        context_json = json.dumps(candidate_places, ensure_ascii=False, indent=2)

        prompt = f"""
너는 지도/교통 도메인에 특화된 추천 엔진이다.

사용자 질문:
\"\"\"{user_question}\"\"\"

아래는 지식 그래프에서 검색된 '후보 장소' 리스트다. (JSON 배열)
각 원소는 하나의 장소 정보를 나타낸다.

후보 장소들:
{context_json}

요구사항:
1. 두 지역({region_a} {district_a}, {region_b} {district_b})에서 모두 접근하기에 공평한 장소를 골라라.
   - 두 지역의 사이에 위치해 있거나, 두 지역 모두에서 비슷한 거리/시간으로 올 수 있을 것 같은 곳을 선호한다.
   - region, district, address 정보를 보고 어느 쪽과 가까운지 추론해도 된다.
2. rating 이 높고 isRecommended == true 인 장소를 우선 고려하라.
3. 최대 {limit}개 장소만 추천해라.
4. 출력은 아래 형식의 JSON 배열로만 반환해라. 추가 설명/텍스트는 절대 쓰지 마.

[
  {{
    "name": "장소 이름",
    "address": "주소",
    "region": "지역 (예: seoul)",
    "district": "구/동 (예: 광진구)",
    "reason": "두 지역의 중간에 있고, 대중교통 접근성이 좋아서 추천한다. ...",
    "score": 0.0
  }}
]
"""

        # LLMResponse.get_response 는 동기 함수이므로, async 환경에서는 thread executor로 보내는게 안전하다.
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, self.llm.get_response, prompt)

        # JSON 파싱 시도
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data[:limit]
            if isinstance(data, dict) and isinstance(data.get("results"), list):
                return data["results"][:limit]
        except json.JSONDecodeError:
            logger.warning("LLM did not return valid JSON", extra={"raw": raw[:300]})

        # JSON 파싱 실패시 raw 를 그대로 감싸서 반환
        return [{"raw": raw}]


# ----------------------------------------------------------------------
# 로컬 테스트용 main
# ----------------------------------------------------------------------


async def _demo() -> None:
    """
    uv run python server/graph_rag.py 로 테스트할 때 사용.

    - 서울/광진구 vs 서울/마포구, 카페 3곳 추천하는 예시.
    """
    graph = await create_graphiti_from_env()
    try:
        rag = PlaceMeetingGraphRAG(graph)

        results = await rag.recommend_meeting_places(
            region_a="seoul",
            district_a="광진구",
            region_b="seoul",
            district_b="광진구",
            category="양식",
            limit=3,
        )

        print(json.dumps(results, ensure_ascii=False, indent=2))
    finally:
        await graph.close()


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_demo())
