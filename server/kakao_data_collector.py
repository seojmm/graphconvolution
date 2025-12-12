#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Kakao Local API collector utilities.

import os
import time
import logging
from typing import Dict, List

import requests
from dotenv import load_dotenv
from models import KakaoPlace

load_dotenv(".env.local")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("kakao_data_collection.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class KakaoDataCollector:
    def __init__(self):
        self.kakao_api_key = os.getenv("KAKAO_REST_API_KEY")
        self.regions = {
            "seoul": {
                "name": "서울",
                "districts": [
                    "강남구",
                    "강동구",
                    "강북구",
                    "강서구",
                    "관악구",
                    "광진구",
                    "구로구",
                    "금천구",
                    "노원구",
                    "도봉구",
                    "동대문구",
                    "동작구",
                    "마포구",
                    "서대문구",
                    "서초구",
                    "성동구",
                    "성북구",
                    "송파구",
                    "양천구",
                    "영등포구",
                    "용산구",
                    "은평구",
                    "종로구",
                    "중구",
                    "중랑구",
                ],
            },
        }
        self.category_mapping = {
            "한식": ["한식"],
            "중식": ["중식"],
            "일식": ["일식"],
            "양식": ["양식"],
            "분식": ["분식"],
            "카페": ["카페"],
            "술집": ["술집"],
        }

    def collect_kakao_data(self, region: str, district: str, category: str) -> List[Dict]:
        """Call Kakao Local search API directly and return parsed restaurant dicts."""
        logger.info(f"카카오맵 수집 시작: {region} - {district} - {category}")
        if not self.kakao_api_key:
            logger.error("KAKAO_REST_API_KEY is missing")
            return []

        restaurants: List[Dict] = []
        page = 1
        url = "https://dapi.kakao.com/v2/local/search/keyword.json"

        while page <= 2:
            try:
                headers = {"Authorization": f"KakaoAK {self.kakao_api_key}"}
                params = {
                    "query": f"{district} {category}",
                    "page": page,
                    "size": 10,
                }
                resp = requests.get(url, headers=headers, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                docs = data.get("documents", [])
                if not docs:
                    break

                for item in docs:
                    parsed = self._parse_kakao_item(item, region, district)
                    if parsed:
                        restaurants.append(parsed)

                page += 1
                time.sleep(0.4)
            except Exception as exc:
                logger.error(f"카카오맵 데이터 수집 오류: {exc}")
                break

        logger.info(f"카카오맵 데이터 수집 완료: {len(restaurants)}개")
        return restaurants

    def _parse_kakao_item(self, item: Dict, region: str, district: str) -> KakaoPlace:
        """Normalize Kakao API response into our PlaceData/KakaoPlace shape."""
        try:
            distance = item.get("distance")
            distance_val = None if distance in (None, "") else str(distance)
            return {
                "id": f"{item.get('id', '')}",
                "placeName": item.get("place_name", ""),
                "placeUrl": item.get("place_url", "") or "",
                "categoryName": item.get("category_name", "") or "",
                "categoryGroupCode": item.get("category_group_code", "") or "",
                "categoryGroupName": item.get("category_group_name", "") or "",
                "phone": item.get("phone", "") or "",
                "addressName": item.get("address_name", ""),
                "roadAddressName": item.get("road_address_name", ""),
                "latitude": float(item.get("y", 0) or 0),
                "longitude": float(item.get("x", 0) or 0),
                "distance": distance_val,
                "region": region,
                "district": district,
                # Default placeholders for downstream schema
                "rating": 0.0,
                "openingHours": "",
                "parking": "",
                "breaktime": "",
                "closedDays": "",
                "priceRange": "",
                "menus": "",
                "notes": "",
                "description": "",
                "isOpen": True,
                "isRecommended": True,
                "source": "kakao",
            }
        except Exception as exc:
            logger.error(f"Failed to parse Kakao item: {exc}")
            return None

    def _deduplicate_restaurants(self, restaurants: List[Dict]) -> List[Dict]:
        """Deduplicate by placeName and addressName."""
        seen = set()
        unique_restaurants: List[Dict] = []
        for restaurant in restaurants:
            key = f"{restaurant['placeName']}_{restaurant['addressName']}"
            if key not in seen:
                seen.add(key)
                unique_restaurants.append(restaurant)
        return unique_restaurants
