import json
import redis
from typing import List
from ..Domain.model import MeetingCandidate
from .session_cache import SessionCache

class RedisSessionCache(SessionCache):
    def __init__(self, client: redis.Redis):
        self.client = client

    def save_candidates(self, request_id: str, candidates: List[MeetingCandidate], ttl_seconds: int) -> None:
        data = [c.model_dump() for c in candidates]
        self.client.setex(request_id, ttl_seconds, json.dumps(data, ensure_ascii=False))

    def load_candidates(self, request_id: str) -> List[MeetingCandidate]:
        raw = self.client.get(request_id)
        if not raw:
            return []
        data = json.loads(raw)
        return [MeetingCandidate(**c) for c in data]
