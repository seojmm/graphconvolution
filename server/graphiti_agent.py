"""Seed Kakao Local place data (Seoul, all districts/categories) into Graphiti with custom entity/edge types from models.py."""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType
from kakao_data_collector import KakaoDataCollector
from models import (
    PlaceEntity,
    PhoneEntity,
    ParkingEntity,
    BreaktimeEntity,
    OpeningHoursEntity,
    ClosedDaysEntity,
    MenuEntity,
    NoteEntity,
    HasPhone,
    HasParking,
    HasBreaktime,
    HasOpeningHours,
    HasClosedDays,
    HasMenu,
    HasNote,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
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


def ensure_env() -> None:
    required = ["OPENAI_API_KEY", "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "KAKAO_REST_API_KEY"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")


def fetch_all_seoul(limit_per_category: Optional[int] = None) -> List[Dict[str, Any]]:
    collector = KakaoDataCollector()
    districts = collector.regions.get("seoul", {}).get("districts", [])
    categories = list(collector.category_mapping.keys())
    all_places: List[Dict[str, Any]] = []

    for district in districts[:10]:
        district_raw: List[Dict[str, Any]] = []
        for category in categories:
            chunk = collector.collect_kakao_data("seoul", district, category)
            district_raw.extend(chunk if limit_per_category is None else chunk[:limit_per_category])
        unique = collector._deduplicate_restaurants(district_raw)
        all_places.extend(unique)
        logger.info("Collected district", extra={"district": district, "count": len(unique)})

    logger.info("Collected all Seoul districts", extra={"total": len(all_places)})
    return all_places


def _rename_for_graph(place: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(place)
    payload["place_name"] = payload.pop("name", "")
    payload["road_address"] = payload.pop("roadAddress", "")
    payload["sub_category"] = payload.pop("subCategory", "")
    payload["opening_hours"] = payload.pop("openingHours", "")
    payload["image_urls"] = payload.pop("imageUrls", [])
    payload["is_open"] = payload.pop("isOpen", None)
    payload["last_updated"] = payload.pop("lastUpdated", None)
    payload["like_count"] = payload.pop("likeCount", 0)
    payload["visit_count"] = payload.pop("visitCount", 0)
    payload["is_recommended"] = payload.pop("isRecommended", False)
    return payload


async def seed_places(graph: Graphiti, places: List[Dict[str, Any]], description: str) -> None:
    count = 0
    for place in places:
        payload = _rename_for_graph(place)
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
        count += 1
    logger.info("Seeded places", extra={"count": count})


async def main() -> None:
    load_dotenv(".env.local")
    ensure_env()

    neo4j_uri = os.environ["NEO4J_URI"]
    neo4j_user = os.environ["NEO4J_USER"]
    neo4j_password = os.environ["NEO4J_PASSWORD"]

    graph = Graphiti(neo4j_uri, neo4j_user, neo4j_password)

    try:
        await graph.build_indices_and_constraints()
        places = fetch_all_seoul(limit_per_category=None)
        await seed_places(graph, places, description="kakao places seoul/all districts/all categories")
    finally:
        await graph.close()


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
