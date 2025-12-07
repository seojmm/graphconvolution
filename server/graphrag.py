"""Graphiti + LLM based GraphRAG demo (clean English version).

Run locally:
    uv run python server/graphrag.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import List, Optional

from dotenv import load_dotenv

from graphiti_core import Graphiti
from graphiti_core.edges import EntityEdge  # noqa: F401  # kept for future use
from graphiti_core.nodes import EntityNode
from graphiti_core.search.search_config_recipes import NODE_HYBRID_SEARCH_RRF
from graphiti_core.search.search_filters import SearchFilters

try:
    from .llm_response import LLMResponse  # package import
except ImportError:  # pragma: no cover - script execution
    from llm_response import LLMResponse  # type: ignore

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Graphiti connection helper
# ----------------------------------------------------------------------


async def create_graphiti_from_env() -> Graphiti:
    """
    Create a Graphiti client using env vars from .env.local.
    """
    load_dotenv(".env.local")

    neo4j_uri = os.environ["NEO4J_URI"]
    neo4j_user = os.environ["NEO4J_USER"]
    neo4j_password = os.environ["NEO4J_PASSWORD"]

    graph = Graphiti(neo4j_uri, neo4j_user, neo4j_password)
    await graph.build_indices_and_constraints()
    return graph


# ----------------------------------------------------------------------
# GraphRAG pipeline
# ----------------------------------------------------------------------


class PlaceMeetingGraphRAG:
    """
    - Search Place nodes in Graphiti.
    - Ask LLM for recommended meeting spots between two regions/districts.
    """

    def __init__(self, graphiti: Graphiti, llm: Optional[LLMResponse] = None):
        self.graphiti = graphiti
        self.llm = llm or LLMResponse()

    async def _search_place_nodes(
        self,
        query: str,
        limit: int = 30,
    ):
        """Hybrid search for Place nodes using Graphiti."""
        search_config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
        search_config.limit = limit

        search_filter = SearchFilters(
            node_labels=["Place"],
        )

        results = await self.graphiti.search(
            query=query,
            config=search_config,
            search_filter=search_filter,
        )
        return results

    @staticmethod
    def _node_to_place_dict(node: EntityNode) -> dict:
        """Flatten EntityNode to a simple dict for LLM/context."""
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

    async def recommend_meeting_places(
        self,
        region_a: str,
        district_a: str,
        region_b: str,
        district_b: str,
        category: str = "cafe",
        limit: int = 3,
    ) -> List[dict]:
        """
        Recommend meeting places between region_a/district_a and region_b/district_b.
        Returns a list[dict] from the LLM (or raw text wrapper on failure).
        """

        user_question = (
            f"Find a good meeting place for groups coming from {region_a} {district_a} "
            f"and {region_b} {district_b}. Prefer category '{category}'. "
            "Balance travel time between both sides."
        )

        # 1) Search in Graphiti
        results = await self._search_place_nodes(user_question, limit=limit * 4)

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

        context_json = json.dumps(candidate_places, ensure_ascii=False, indent=2)

        prompt = f"""
You are a meeting place recommender.

User question:
\"\"\"{user_question}\"\"\"

Candidate places (JSON array):
{context_json}

Instructions:
1. Pick places that balance travel between both sides ({region_a} {district_a} vs {region_b} {district_b}).
2. Prefer isRecommended == true and higher rating if available.
3. Return only the top {limit} places as a JSON array with fields: name, address, region, district, reason, score.
"""

        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, self.llm.get_response, prompt)

        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data[:limit]
            if isinstance(data, dict) and isinstance(data.get("results"), list):
                return data["results"][:limit]
        except json.JSONDecodeError:
            logger.warning("LLM did not return valid JSON", extra={"raw": raw[:300]})

        return [{"raw": raw}]


# ----------------------------------------------------------------------
# Local CLI demo
# ----------------------------------------------------------------------


async def _demo() -> None:
    """CLI demo for quick testing."""
    graph = await create_graphiti_from_env()
    try:
        rag = PlaceMeetingGraphRAG(graph)
        results = await rag.recommend_meeting_places(
            region_a="seoul",
            district_a="gangnam-gu",
            region_b="seoul",
            district_b="mapo-gu",
            category="cafe",
            limit=3,
        )
        print(json.dumps(results, ensure_ascii=False, indent=2))
    finally:
        await graph.close()


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_demo())
