
from abc import ABC, abstractmethod
from typing import List
from ..Domain.model import MeetingCandidate


class SessionCache(ABC):
    """Query Graph를 Redis 등에 저장/조회하기 위한 포트."""

    @abstractmethod
    def save_candidates(self, request_id: str, candidates: List[MeetingCandidate], ttl_seconds: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def load_candidates(self, request_id: str) -> List[MeetingCandidate]:
        raise NotImplementedError
