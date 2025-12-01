from typing import List, Optional, Dict
from pydantic import BaseModel, Field


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
    home_anchor: Optional[str] = None  # e.g. "서울역", "잠실역"


class UserRequest(BaseModel):
    user_query: str
    user_id: str
    participants: List[Participant] = Field(default_factory=list)


class EtaStats(BaseModel):
    avg: Optional[int] = None
    max: Optional[int] = None
    std: Optional[float] = None



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


class Metrics(BaseModel):
    eta_avg: Optional[float] = None
    eta_max: Optional[float] = None
    eta_std: Optional[float] = None
    open_hours_score: Optional[float] = None
    budget_score: Optional[float] = None
    pref_match_score: Optional[float] = None
    final_score: Optional[float] = None


class MeetingCandidate(BaseModel):
    # 식별자 계층
    id: str               # = MeetingCandidate 하이퍼엣지 ID
    request_id: str       # 같은 질의에서 생성된 후보를 묶는 ID

    # 연결 대상 키
    place_name: str
    place_id: str
    address: str
    timeslot_id: Optional[str] = None
    area_id: Optional[str] = None
    attendee_pids: List[str] = []

    # 시간/라이프사이클
    start_time: str            # ISO
    end_time: str              # ISO
    created_at: Optional[str] = None
    ttl: Optional[int] = None  # 초 단위 TTL (Redis Query Graph용)

    # 평가/지표
    estimated_price_per_person: Optional[int] = None
    eta_stats: Optional[EtaStats] = None
    fairness_score: Optional[float] = None
    satisfaction_score: Optional[float] = None

    metrics: Optional[Metrics] = None
    reasoning: str = ""