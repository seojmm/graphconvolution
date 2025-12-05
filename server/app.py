"""FastAPI service that proxies Kakao Map place searches."""

from datetime import datetime
import html
import json
import logging
import re
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
import requests

from .kakao_data_collector import KakaoDataCollector
from .llm_response import LLMResponse
from .models import (
    DaumBlogResult,
    DaumCafeResult,
    DaumWebResult,
    ExtractResponse,
    KakaoGeocodeResult,
    KakaoPlace,
    PlaceData,
    PlacesResponse,
)


logger = logging.getLogger(__name__)
collector = KakaoDataCollector()
llm_client = LLMResponse()

app = FastAPI(title="Kakao Places Proxy", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    if not llm_client.kanana_api_key:
        raise HTTPException(status_code=500, detail="KANANA_API_KEY is not configured.")


def _collect_places(region: str, district: str, categories: List[str]) -> List[PlaceData]:
    _ensure_api_key()
    _validate_inputs(region, district, categories)

    collected = []
    for category in categories:
        collected.extend(collector.collect_kakao_data(region, district, category))

    unique = collector._deduplicate_restaurants(collected)
    enriched = [collector._enrich_restaurant_data(item) for item in unique]
    return enriched


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


def _parse_place(item: dict) -> KakaoPlace:
    distance_value = item.get("distance")
    distance_int = None
    if distance_value not in (None, ""):
        try:
            distance_int = int(distance_value)
        except ValueError:
            distance_int = None

    return KakaoPlace(
        id=item.get("id", ""),
        name=item.get("place_name", ""),
        category=item.get("category_name", ""),
        categoryGroupCode=item.get("category_group_code", "") or "",
        categoryGroupName=item.get("category_group_name", "") or "",
        phone=item.get("phone", "") or "",
        address=item.get("address_name", "") or "",
        roadAddress=item.get("road_address_name", "") or "",
        latitude=float(item.get("y", 0)),
        longitude=float(item.get("x", 0)),
        placeUrl=item.get("place_url", "") or "",
        distance=distance_int,
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
    query: str = Query(..., description="Keyword to search."),
    x: Optional[float] = Query(None, description="Longitude for proximity search."),
    y: Optional[float] = Query(None, description="Latitude for proximity search."),
    radius: Optional[int] = Query(None, description="Radius in meters (10~20000) when x,y provided."),
    size: int = Query(15, ge=1, le=45, description="Number of results (max 45)."),
):
    params = {"query": query, "size": size}
    if x is not None and y is not None:
        params.update({"x": x, "y": y})
        if radius is not None:
            params["radius"] = radius

    try:
        data = await run_in_threadpool(_kakao_request, "/v2/local/search/keyword.json", params)
    except HTTPException:
        raise

    documents = data.get("documents") or []
    return [_parse_place(doc) for doc in documents]


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
    size: int = Query(5, ge=1, le=50, description="Number of results per page."),
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
    size: int = Query(5, ge=1, le=50, description="Number of results per page."),
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
    sort: str = Query("recency", description="Sort by 'accuracy' or 'recency'."),
    page: int = Query(1, ge=1, le=5, description="Page number (kept small to limit payload)."),
    size: int = Query(5, ge=1, le=10, description="Results per source to aggregate."),
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
        "너는 한 장소(쿼리에 포함된 상호와 주소)에 대한 정보만 추출하는 도우미다. "
        "입력은 Daum web/blog/cafe 검색의 내용 일부이며 HTML 태그가 제거된 텍스트다. "
        "쿼리에 포함된 상호/주소와 직접 관련 없는 다른 장소, 사람, 숫자는 모두 무시한다. "
        "반드시 JSON 하나만 출력한다. 최소로 parking, breaktime, openingHours, closedDays, priceRange, menus, notes 키를 포함해야 하며, "
        "이 키는 문자열로 채운다(정보가 없으면 빈 문자열). 다른 유용한 정보가 있으면 추가 키로 포함해도 된다. "
        "추가 설명 문구 없이 JSON만 반환한다."
    )
    prompt = (
        f"{system_prompt}\n\n"
        f"[쿼리]\n{query}\n\n"
        f"[연결된 contents]\n{combined}\n\n"
        "위 내용 중 쿼리와 동일한 장소에 관한 정보만 JSON으로 추출해."
    )

    llm_output = await run_in_threadpool(llm_client.get_response, prompt)

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


@app.on_event("startup")
def log_configuration():
    if collector.kakao_api_key:
        logger.info("Kakao REST API key is loaded.")
    else:
        logger.warning("Kakao REST API key is missing; API requests will fail.")


__all__ = ["app"]




