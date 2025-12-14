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

class SafeOpenAIGenericClient(OpenAIGenericClient):
    """OpenAI client with defensive JSON parsing to avoid hard failures on malformed responses."""

    def _safe_json_loads(self, text: str) -> Dict[str, Any]:
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                        result = json.loads(text[start : end + 1])
                        # fall through to post-processing
                except Exception:
                    pass
            logger.warning(
                "Failed to parse LLM JSON; returning empty dict.",
                extra={"preview": text[:500]},
            )
            result = {}

        if isinstance(result, dict) and "extracted_entities" not in result:
            result["extracted_entities"] = []
        return result

    async def _generate_response(
        self,
        messages: list,
        response_model: Any | None = None,
        max_tokens: int = 1024,
        model_size: Any = None,
    ) -> Dict[str, Any]:
        try:
            response = await self.client.chat.completions.create(
                model=self.model or "gpt-4.1-mini",
                messages=[{"role": m.role, "content": getattr(m, "content", "")} for m in messages],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or ""
            return self._safe_json_loads(raw)
        except Exception:
            logger.warning("LLM response failed or JSON decode failed; returning empty dict.", exc_info=True)
            return {}

from kakao_data_collector import KakaoDataCollector

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
# entity_types = {
#     "Place": PlaceEntity,
#     "Phone": PhoneEntity,
#     "Parking": ParkingEntity,
#     "Breaktime": BreaktimeEntity,
#     "OpeningHours": OpeningHoursEntity,
#     "ClosedDays": ClosedDaysEntity,
#     "Menu": MenuEntity,
#     "Note": NoteEntity,
#     "PriceRange": PriceRangeEntity,
# }

# edge_types = {
#     "HAS_PHONE": HasPhone,
#     "HAS_PARKING": HasParking,
#     "HAS_BREAKTIME": HasBreaktime,
#     "HAS_OPENING_HOURS": HasOpeningHours,
#     "HAS_CLOSED_DAYS": HasClosedDays,
#     "HAS_MENU": HasMenu,
#     "HAS_NOTE": HasNote,
#     "HAS_PRICE_RANGE": HasPriceRange,
# }

# edge_type_map = {
#     ("Place", "Phone"): ["HAS_PHONE"],
#     ("Place", "Parking"): ["HAS_PARKING"],
#     ("Place", "Breaktime"): ["HAS_BREAKTIME"],
#     ("Place", "OpeningHours"): ["HAS_OPENING_HOURS"],
#     ("Place", "ClosedDays"): ["HAS_CLOSED_DAYS"],
#     ("Place", "Menu"): ["HAS_MENU"],
#     ("Place", "Note"): ["HAS_NOTE"],
#     ("Place", "PriceRange"): ["HAS_PRICE_RANGE"],
# }


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

def _as_str(val):
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    return str(val)

def _coerce_body_scalars(body: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure all episode body values are Neo4j-friendly primitives (str/number/bool/None)."""
    safe: Dict[str, Any] = {}
    for k, v in body.items():
        if v is None or isinstance(v, (str, int, float, bool)):
            safe[k] = v
        elif isinstance(v, (dict, list)):
            safe[k] = json.dumps(v, ensure_ascii=False)
        else:
            safe[k] = str(v)
    return safe

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

    def _build_episode_body(self, place: Dict[str, Any]) -> str:
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

        safe_body = _coerce_body_scalars(body)
        return json.dumps(safe_body, ensure_ascii=False)

    async def upsert_place(
        self,
        place: Dict[str, Any],
        description: str,
    ) -> None:
        payload = self._build_episode_body(place)
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
            previous_episode_uuids=(previous_uuids[:1] if previous_uuids else None),
        )
        print(f"Upserted place: {place.get('placeName')} ({len(previous_uuids)} previous episodes linked)")


class KakaoGraphitiAgent:
    """End-to-end agent from Kakao seed -> Kanana enrichment -> Graphiti upsert."""

    def __init__(
        self,
        graph: Graphiti,
        collector: KakaoDataCollector,
        max_turns: int = 3,
        limit_per_category: Optional[int] = None,
    ):
        self.graph = graph
        self.collector = collector
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


    async def run(
        self,
        region: str,
        districts: Sequence[str],
        categories: Sequence[str],
    ) -> None:
        places = self._collect_places(region, districts, categories)
        for place in places:
            description = (
                f"kakao:{region}/{place.get('district')}:{place.get('category')}"
            )
            await self.upserter.upsert_place(place, None, description)

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
        llm_client=SafeOpenAIGenericClient(config=llm_config, max_tokens=llm_max_tokens),
    )

    agent = KakaoGraphitiAgent(
        graph=graph,
        collector=collector,
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
