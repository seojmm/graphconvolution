from datetime import datetime
from typing import List

from pydantic import BaseModel


class Place(BaseModel):
    id: str
    name: str
    latitude: float
    longitude: float
    address: str
    roadAddress: str
    category: str
    subCategory: str
    phone: str
    rating: float
    reviewCount: int
    openingHours: str
    region: str
    district: str
    tags: List[str]
    description: str
    mission: str
    reward: int
    isOpen: bool
    lastUpdated: datetime
    imageUrls: List[str]
    likeCount: int
    visitCount: int
    isRecommended: bool
    source: str


class PlacesResponse(BaseModel):
    region: str
    district: str
    categories: List[str]
    total: int
    items: List[Place]



class KakaoGeocodeResult(BaseModel):
    addressName: str
    roadAddressName: str
    latitude: float
    longitude: float
    raw: dict | None = None


class KakaoPlace(BaseModel):
    id: str
    name: str
    category: str
    categoryGroupCode: str
    categoryGroupName: str
    phone: str
    address: str
    roadAddress: str
    latitude: float
    longitude: float
    placeUrl: str
    distance: int | None = None


# Daum 검색 결과 모델

class DaumWebResult(BaseModel):
    meta: dict
    documents: List[dict]


class DaumBlogResult(BaseModel):
    meta: dict
    documents: List[dict]
    

class DaumCafeResult(BaseModel):
    meta: dict
    documents: List[dict]


class ExtractResponse(BaseModel):
    query: str
    combinedContents: str
    llmResult: dict | str
    sourceCounts: dict
