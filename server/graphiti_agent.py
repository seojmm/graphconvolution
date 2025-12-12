"""Agentic Kakao -> Kanana enrichment -> Graphiti upsert pipeline."""

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from dotenv import load_dotenv
from tqdm import tqdm

from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient

from kakao_data_collector import KakaoDataCollector
from extraction_agent import PlaceEnrichmentAgent
from models import (
    PlaceEntity,
    PhoneEntity,
    ParkingEntity,
    BreaktimeEntity,
    OpeningHoursEntity,
    ClosedDaysEntity,
    MenuEntity,
    NoteEntity,
    PriceRangeEntity,
    HasPhone,
    HasParking,
    HasBreaktime,
    HasOpeningHours,
    HasClosedDays,
    HasMenu,
    HasNote,
    HasPriceRange,
    ExtractAgentRequest,
)

LOG_FILE = os.path.join(os.path.dirname(__file__), "graphiti_agent.log")

# Log to both console and a persistent file for each run.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# Custom entity/edge registrations sourced from models.py
entity_types = {
    "Place": PlaceEntity,
    "Phone": PhoneEntity,
    "Parking": ParkingEntity,
    "Breaktime": BreaktimeEntity,
    "OpeningHours": OpeningHoursEntity,
    "ClosedDays": ClosedDaysEntity,
    "Menu": MenuEntity,
    "Note": NoteEntity,
    "PriceRange": PriceRangeEntity,
}

edge_types = {
    "HAS_PHONE": HasPhone,
    "HAS_PARKING": HasParking,
    "HAS_BREAKTIME": HasBreaktime,
    "HAS_OPENING_HOURS": HasOpeningHours,
    "HAS_CLOSED_DAYS": HasClosedDays,
    "HAS_MENU": HasMenu,
    "HAS_NOTE": HasNote,
    "HAS_PRICE_RANGE": HasPriceRange,
}

edge_type_map = {
    ("Place", "Phone"): ["HAS_PHONE"],
    ("Place", "Parking"): ["HAS_PARKING"],
    ("Place", "Breaktime"): ["HAS_BREAKTIME"],
    ("Place", "OpeningHours"): ["HAS_OPENING_HOURS"],
    ("Place", "ClosedDays"): ["HAS_CLOSED_DAYS"],
    ("Place", "Menu"): ["HAS_MENU"],
    ("Place", "Note"): ["HAS_NOTE"],
    ("Place", "PriceRange"): ["HAS_PRICE_RANGE"],
}


def ensure_env() -> None:
    required = ["KAKAO_REST_API_KEY", "NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")
    if not (os.getenv("KANANA_API_KEY") or os.getenv("OPENAI_API_KEY")):
        raise ValueError("Missing LLM API key: set KANANA_API_KEY or OPENAI_API_KEY.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agentic Kakao -> Graphiti loader with Kanana enrichment.")
    parser.add_argument("--region", default="seoul", help="Region key defined in KakaoDataCollector.")
    parser.add_argument(
        "--district",
        action="append",
        help="District name (repeatable). If omitted, all districts for the region are used.",
    )
    parser.add_argument(
        "--category",
        action="append",
        help="Category name (repeatable). If omitted, all categories are used.",
    )
    parser.add_argument(
        "--limit-per-category",
        type=int,
        default=3,
        help="Max places per category per district. 0 or negative to disable the limit.",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=3,
        help="Max agent turns (base + follow-ups) per place.",
    )
    parser.add_argument(
        "--base-size",
        type=int,
        default=5,
        help="Number of documents per Daum source for the base query.",
    )
    parser.add_argument(
        "--follow-up-size",
        type=int,
        default=3,
        help="Number of documents per Daum source for field-specific follow-up queries.",
    )
    parser.add_argument(
        "--kanana-model",
        default="kanana-2-30b",
        help="Model name for Kanana/OpenAI compatible endpoint. Defaults to KANANA_MODEL/OPENAI_MODEL or gpt-4o-mini.",
    )
    parser.add_argument(
        "--kanana-base-url",
        default=None,
        help="Custom base URL for Kanana/OpenAI compatible endpoint. Defaults to KANANA_BASE_URL/OPENAI_BASE_URL.",
    )
    return parser.parse_args()


class GraphitiUpserter:
    """Handles upsert semantics against Graphiti by linking to prior episodes when present."""

    def __init__(self, graph: Graphiti):
        self.graph = graph

    async def _find_previous_episode_uuids(self, place_name: str, address: Optional[str]) -> List[str]:
        query = " ".join(filter(None, [place_name, address]))
        if not query:
            return []

        try:
            edges = await self.graph.search(query=query, num_results=1)
        except Exception:
            logger.exception("Graphiti search failed while looking for existing place", extra={"query": query})
            return []

        uuids: List[str] = []
        for edge in edges or []:
            for ep in getattr(edge, "episodes", []) or []:
                uuid_val = ep.get("uuid") if isinstance(ep, dict) else getattr(ep, "uuid", None)
                if uuid_val:
                    uuids.append(uuid_val)
                    break  # keep only the most recent match to limit prompt size
        return list(dict.fromkeys(uuids))[:1]

    def _build_episode_body(self, place: Dict[str, Any], enriched: Dict[str, Any]) -> str:
        body = {
            "place_name": place.get("placeName") or place.get("name") or "",
            "address": place.get("addressName", ""),
            "road_address": place.get("roadAddressName", ""),
            "region": place.get("region"),
            "district": place.get("district"),
            "category": place.get("categoryName") or place.get("category"),
            "sub_category": place.get("subCategory") or place.get("categoryGroupName"),
            "latitude": place.get("latitude") or place.get("y"),
            "longitude": place.get("longitude") or place.get("x"),
            "kakao_id": place.get("id"),
            "place_url": place.get("placeUrl"),
            "phone_number": place.get("phone"),
            "rating": place.get("rating"),
            "distance": place.get("distance"),
            "is_open": place.get("isOpen"),
            "is_recommended": place.get("isRecommended"),
            "source": place.get("source") or "kakao",
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }

        if isinstance(enriched, dict):
            body.update(
                {
                    "parking_status": enriched.get("parking"),
                    "breaktime": enriched.get("breaktime"),
                    "opening_hours": enriched.get("openingHours"),
                    "closed_days": enriched.get("closedDays"),
                    "price_range": enriched.get("priceRange"),
                    "menus": enriched.get("menus"),
                    "notes": enriched.get("notes"),
                }
            )
        return json.dumps(body, ensure_ascii=False)

    async def upsert_place(
        self,
        place: Dict[str, Any],
        enriched: Dict[str, Any],
        description: str,
    ) -> None:
        payload = self._build_episode_body(place, enriched)
        previous_uuids = await self._find_previous_episode_uuids(
            place_name=place.get("placeName") or place.get("name") or "",
            address=place.get("roadAddressName") or place.get("addressName"),
        )

        await self.graph.add_episode(
            name=place.get("placeName") or "place",
            episode_body=payload,
            source=EpisodeType.json,
            source_description=description,
            reference_time=datetime.now(timezone.utc),
            entity_types=entity_types,
            edge_types=edge_types,
            edge_type_map=edge_type_map,
            previous_episode_uuids=(previous_uuids[:1] if previous_uuids else None),
        )
        print(f"Upserted place: {place.get('placeName')} ({len(previous_uuids)} previous episodes linked)")


class KakaoGraphitiAgent:
    """End-to-end agent from Kakao seed -> Kanana enrichment -> Graphiti upsert."""

    def __init__(
        self,
        graph: Graphiti,
        collector: KakaoDataCollector,
        enricher: PlaceEnrichmentAgent,
        max_turns: int = 3,
        limit_per_category: Optional[int] = None,
    ):
        self.graph = graph
        self.collector = collector
        self.enricher = enricher
        self.max_turns = max_turns
        self.limit_per_category = limit_per_category if limit_per_category and limit_per_category > 0 else None
        self.upserter = GraphitiUpserter(graph)

    def _collect_places(
        self,
        region: str,
        districts: Sequence[str],
        categories: Sequence[str],
    ) -> List[Dict[str, Any]]:
        all_places: List[Dict[str, Any]] = []
        for district in tqdm(districts, desc="Districts", unit="district"):
            district_raw: List[Dict[str, Any]] = []
            for category in tqdm(categories, desc=f"{district} categories", unit="category", leave=False):
                chunk = self.collector.collect_kakao_data(region, district, category)
                if self.limit_per_category:
                    chunk = chunk[: self.limit_per_category]
                for item in chunk:
                    item.setdefault("region", region)
                    item.setdefault("district", district)
                    item.setdefault("category", category)
                district_raw.extend(chunk)

            unique = self.collector._deduplicate_restaurants(district_raw)
            all_places.extend(unique)
            logger.info("Collected district", extra={"district": district, "count": len(unique)})

        logger.info("Collected all districts", extra={"total": len(all_places)})
        return all_places

    async def _enrich_place(self, place: Dict[str, Any]) -> Dict[str, Any]:
        agent_req = ExtractAgentRequest(
            query="주차, 브레이크타임, 영업시간, 휴무일, 가격대, 메뉴, 비고 정보",
            place=place.get("placeName") or place.get("name"),
            address=place.get("roadAddressName") or place.get("addressName"),
            region=place.get("region"),
            district=place.get("district"),
            category=place.get("category"),
            maxTurns=self.max_turns,
            size=self.enricher.base_size,
        )
        result = await asyncio.to_thread(self.enricher.run, agent_req)
        return result.llmResult if isinstance(result.llmResult, dict) else {}

    async def run(
        self,
        region: str,
        districts: Sequence[str],
        categories: Sequence[str],
    ) -> None:
        places = self._collect_places(region, districts, categories)
        for place in places:
            enriched = await self._enrich_place(place)
            description = (
                f"kakao:{region}/{place.get('district')}:{place.get('category')} + kanana agent enrichment"
            )
            await self.upserter.upsert_place(place, enriched, description)


graphiti_client: Graphiti | None = None  # compatibility for FastAPI /graph/search endpoint


async def init_client() -> None:
    return None


async def run_custom_agent_demo(query: str) -> List[str]:
    return [f"Graphiti agent demo is now handled via the CLI script. Query: {query}"]


async def main() -> None:
    load_dotenv(".env.local")
    ensure_env()

    args = _parse_args()

    collector = KakaoDataCollector()
    categories = args.category or list(collector.category_mapping.keys())
    districts = args.district or collector.regions.get(args.region, {}).get("districts", [])
    if not districts:
        raise ValueError(f"No districts configured for region '{args.region}'.")

    llm_base_url = args.kanana_base_url or os.getenv("KANANA_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    llm_api_key = os.getenv("KANANA_API_KEY") or os.getenv("OPENAI_API_KEY")

    # Cap completion tokens to avoid Kanana context overflow errors.
    llm_max_tokens = 1024
    llm_config = LLMConfig(
        api_key=llm_api_key,
        model="kanana-2-30b-a3b-instruct",
        base_url=llm_base_url,
        max_tokens=llm_max_tokens,
    )
    graph = Graphiti(
        os.environ["NEO4J_URI"],
        os.environ["NEO4J_USERNAME"],
        os.environ["NEO4J_PASSWORD"],
        llm_client=OpenAIGenericClient(config=llm_config, max_tokens=llm_max_tokens),
    )
    enricher = PlaceEnrichmentAgent(
        base_size=args.base_size,
        follow_up_size=args.follow_up_size,
    )
    agent = KakaoGraphitiAgent(
        graph=graph,
        collector=collector,
        enricher=enricher,
        max_turns=args.max_turns,
        limit_per_category=args.limit_per_category,
    )

    try:
        await graph.build_indices_and_constraints()
        await agent.run(args.region, districts, categories)
    finally:
        await graph.close()


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
