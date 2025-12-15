from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

import os
import requests


class MidpointService(ABC):
    """출발지 리스트를 받아 만남 후보 지역(역/동 등)을 반환하는 포트."""

    @abstractmethod
    def suggest_meeting_areas(self, departure_points: List[str]) -> List[str]:
        raise NotImplementedError


class DummyMidpointService(MidpointService):
    """MCP 연동 전까지 사용할 더미 구현."""

    def suggest_meeting_areas(self, departure_points: List[str]) -> List[str]:
        # 간단히 강남역을 기본값으로 반환 (실제 구현 시 MCP/지도 API 연동)
        return ["강남역"] if departure_points else []


class KakaoMapMidpointService(MidpointService):
    """
    카카오맵 REST API로 출발지 좌표를 조회하고 단순 centroid로 중간지점을 계산.
    - REST 키: KAKAO_REST_API_KEY (필수)
    - 검색: keyword API, 역지오코딩: coord2regioncode API를 기본으로 사용
    """

    def __init__(
        self,
        rest_api_key: Optional[str] = None,
        search_url: str = "https://dapi.kakao.com/v2/local/search/keyword.json",
        reverse_geocode_url: str = "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json",
    ):
        self.rest_api_key = rest_api_key or os.getenv("KAKAO_REST_API_KEY")
        self.search_url = search_url
        self.reverse_geocode_url = reverse_geocode_url

    def suggest_meeting_areas(self, departure_points: List[str]) -> List[str]:
        if not departure_points or not self.rest_api_key:
            return []

        coords: List[Tuple[float, float]] = []
        for point in departure_points:
            c = self._search_coords(point)
            if c:
                coords.append(c)

        if not coords:
            return []

        lat = sum(c[0] for c in coords) / len(coords)
        lon = sum(c[1] for c in coords) / len(coords)

        area = self._reverse_geocode(lat, lon)

        # 좌표만 반환해야 할 때는 딕셔너리로 반환 (기본 반경 5km 포함)
        return [{"name": f"{area}", "lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "radius_km": 5.0}]

    # ------------------------------
    # 내부 유틸
    # ------------------------------
    def _headers(self) -> dict:
        return {"Authorization": f"KakaoAK {self.rest_api_key}"}

    def _search_coords(self, query: str) -> Optional[Tuple[float, float]]:
        try:
            resp = requests.get(
                self.search_url,
                params={"query": query, "size": 1},
                headers=self._headers(),
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()
            docs = data.get("documents") or []
            if not docs:
                return None
            doc = docs[0]
            lat = float(doc["y"])
            lon = float(doc["x"])
            return (lat, lon)
        except Exception:
            return None

    def _reverse_geocode(self, lat: float, lon: float) -> Optional[str]:
        try:
            resp = requests.get(
                self.reverse_geocode_url,
                params={"y": lat, "x": lon},
                headers=self._headers(),
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()
            docs = data.get("documents") or []
            if not docs:
                return None
            doc = docs[0]
            parts = [
                doc.get("region_1depth_name"),
                doc.get("region_2depth_name"),
                doc.get("region_3depth_name"),
            ]
            area = " ".join([p for p in parts if p])
            return area or None
        except Exception:
            return None
