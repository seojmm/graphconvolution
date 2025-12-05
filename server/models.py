from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


# ---------- API response models ----------

class PlaceData(BaseModel):
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
    items: List[PlaceData]


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


# ---------- Graphiti custom entity/edge schemas ----------

class PlaceEntity(BaseModel):
    place_name: Optional[str] = None
    address: Optional[str] = None
    road_address: Optional[str] = None
    region: Optional[str] = None
    district: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class PhoneEntity(BaseModel):
    number: Optional[str] = None


class ParkingEntity(BaseModel):
    status: Optional[str] = None


class BreaktimeEntity(BaseModel):
    value: Optional[str] = None


class OpeningHoursEntity(BaseModel):
    value: Optional[str] = None


class ClosedDaysEntity(BaseModel):
    value: Optional[str] = None


class MenuEntity(BaseModel):
    value: Optional[str] = None


class NoteEntity(BaseModel):
    value: Optional[str] = None


class HasPhone(BaseModel):
    info: Optional[str] = None


class HasParking(BaseModel):
    info: Optional[str] = None


class HasBreaktime(BaseModel):
    info: Optional[str] = None


class HasOpeningHours(BaseModel):
    info: Optional[str] = None


class HasClosedDays(BaseModel):
    info: Optional[str] = None


class HasMenu(BaseModel):
    info: Optional[str] = None


class HasNote(BaseModel):
    info: Optional[str] = None
