from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field
from enum import Enum

# ---------- API response models ----------

class CategoryGroupCode(Enum):
    MT1 = "대형마트"
    CS2 = "편의점"
    PS3 = "어린이집, 유치원"
    SC4 = "학교"
    AC5 = "학원"
    PK6 = "주차장"
    OL7 = "주유소, 충전소"
    SW8 = "지하철역"
    BK9 = "은행"
    CT1 = "문화시설"
    AG2 = "중개업소"
    PO3 = "공공기관"
    AT4 = "관광명소"
    AD5 = "숙박"
    FD6 = "음식점"
    CE7 = "카페"
    HP8 = "병원"
    PM9 = "약국"

class KakaoPlace(BaseModel):
    id: str
    placeName: str
    placeUrl: str
    categoryName: str
    categoryGroupCode: str
    categoryGroupName: str
    phone: str
    addressName: str
    roadAddressName: str
    latitude: float
    longitude: float
    distance: str | None = None

class PlaceData(KakaoPlace):
    # KakaoPlace 상속
    parking: str
    breaktime: str
    openingHours: str
    closedDays: str
    priceRange: str
    menus: str
    notes: str
    rating: float
    description: str
    isOpen: bool
    isRecommended: bool


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


# ============ Daum search API models ============
class DaumSearchItem(BaseModel):
    contents: str
    datetime: str
    title: str
    url: str

class DaumWebResult(BaseModel):
    meta: dict
    documents: List[DaumSearchItem]


class DaumBlogResult(BaseModel):
    meta: dict
    documents: List[DaumSearchItem]


class DaumCafeResult(BaseModel):
    meta: dict
    documents: List[DaumSearchItem]


class ExtractResponse(BaseModel):
    query: str
    combinedContents: str
    llmResult: dict | str
    sourceCounts: dict


# ---------- Orchestrator (MCP) models ----------

class DateRange(BaseModel):
    """Represents a date constraint for the meeting."""
    type: str  # "single_day" | "multi_day" | "weekday_pattern"
    start_date: Optional[str] = None  # "YYYY-MM-DD"
    end_date: Optional[str] = None    # "YYYY-MM-DD"


class TimeRange(BaseModel):
    """Represents a time-of-day constraint."""
    start_time: Optional[str] = None  # "HH:MM"
    end_time: Optional[str] = None    # "HH:MM"


class BudgetPerPerson(BaseModel):
    max: Optional[int] = None
    currency: str = "KRW"


class Constraints(BaseModel):
    people_count: Optional[int] = None
    area: List[str] = Field(default_factory=list)
    date_range: DateRange = DateRange(type="single_day")
    time_range: TimeRange = TimeRange()
    budget_per_person: BudgetPerPerson = BudgetPerPerson()
    category_preferences: List[str] = Field(default_factory=list)
    hard_constraints: List[str] = Field(default_factory=list)
    soft_constraints: List[str] = Field(default_factory=list)
    raw_normalized_text: str = ""


class Participant(BaseModel):
    participant_id: str
    name: Optional[str] = None
    home_anchor: Optional[str] = None


class UserRequest(BaseModel):
    user_query: str
    user_id: str
    participants: List[Participant] = Field(default_factory=list)


class EtaStats(BaseModel):
    avg: Optional[int] = None
    max: Optional[int] = None
    std: Optional[float] = None


class Metrics(BaseModel):
    eta_avg: Optional[float] = None
    eta_max: Optional[float] = None
    eta_std: Optional[float] = None
    open_hours_score: Optional[float] = None
    budget_score: Optional[float] = None
    pref_match_score: Optional[float] = None
    final_score: Optional[float] = None


class MeetingCandidate(BaseModel):
    id: str
    request_id: str
    place_name: str
    place_id: str
    address: str
    timeslot_id: Optional[str] = None
    area_id: Optional[str] = None
    attendee_pids: List[str] = Field(default_factory=list)
    start_time: str
    end_time: str
    created_at: Optional[str] = None
    ttl: Optional[int] = None
    estimated_price_per_person: Optional[int] = None
    eta_stats: Optional[EtaStats] = None
    fairness_score: Optional[float] = None
    satisfaction_score: Optional[float] = None
    metrics: Optional[Metrics] = None
    reasoning: str = ""


class OrchestratorResult(BaseModel):
    constraints: Constraints
    candidates: List[MeetingCandidate]


class ScheduleRequest(BaseModel):
    user_request: UserRequest
    selected_candidate: MeetingCandidate


class ScheduleResult(BaseModel):
    status: str
    event_id: str
    candidate_id: str


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
