"""FastAPI service that proxies Kakao Map place searches."""

from datetime import datetime
import html
import json
import logging
import os
import re
from typing import List, Optional, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
import requests


from graphiti_core import Graphiti
from .kakao_data_collector import KakaoDataCollector
from .llm_response import LLMResponse
from . import graphiti_agent as graph_agent
from .models import (
    CategoryGroupCode,
    DaumBlogResult,
    DaumCafeResult,
    DaumWebResult,
    ExtractResponse,
    KakaoGeocodeResult,
    KakaoPlace,
    PlaceData,
    PlacesResponse,
    OrchestratorResult,
    ScheduleResult,
    ScheduleRequest,
    UserRequest,
)
from .orchestrator_components import build_orchestrator


logger = logging.getLogger(__name__)
collector = KakaoDataCollector()
kanana_client = LLMResponse(model="kanana-2-30b")
orchestrator = build_orchestrator()
graph_client: Graphiti | None = None

app = FastAPI(title="Kakao Places Proxy", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    if not kanana_client.api_key:
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


def _edge_to_dict(edge: Any) -> dict:
    fields = [
        "fact",
        "score",
        "source_node_uuid",
        "target_node_uuid",
        "edge_uuid",
        "edge_type",
        "source_node_name",
        "target_node_name",
        "invalid_at",
    ]
    return {field: getattr(edge, field, None) for field in fields}


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


@app.get("/graph/search")
async def graph_search(
    query: str = Query(..., description="Natural language query for Graph RAG search."),
    limit: int = Query(5, ge=1, le=20, description="(unused) kept for backward compatibility."),
    center_node_uuid: Optional[str] = Query(None, description="(unused) kept for backward compatibility."),
):
    """Run the LangGraph-based agent demo and return its conversation transcript."""
    try:
        if graph_agent.graphiti_client is None:
            await graph_agent.init_client()
        transcript = await graph_agent.run_custom_agent_demo(query)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Graph agent run failed.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"query": query, "transcript": transcript}


# ------------------------------
# MCP Orchestrator endpoints
# ------------------------------


@app.post("/orchestrate", response_model=OrchestratorResult)
async def orchestrate(body: UserRequest):
    """Plan meeting candidates using the MCP orchestrator."""
    return orchestrator.plan(body)


@app.post("/schedule", response_model=ScheduleResult)
async def schedule_meeting(body: ScheduleRequest):
    """Schedule a selected meeting candidate (demo implementation)."""
    return orchestrator.schedule(body.user_request, body.selected_candidate)


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


__all__ = ["app"]
