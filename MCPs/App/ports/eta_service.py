import json
import re
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from ..Domain.model import Participant, MeetingCandidate, EtaStats
from MCPs.kakao_mcp import PlayMCPClient

class EtaService(ABC):
    @abstractmethod
    def estimate_eta_stats(
        self,
        participants: List[Participant],
        candidate: MeetingCandidate,
    ) -> EtaStats:
        raise NotImplementedError


class KakaoMapEtaService(EtaService):
    """
    카카오맵 MCP를 통해 ETA를 계산하는 구현체.
    """

    def __init__(
        self,
        kakaomap_mcp_client: PlayMCPClient,
        tool_name: str = "KakaoMap-GetPublicTransitDirections",  # ← 네가 말한 그 이름을 기본값으로 둔다
    ) -> None:
        self.client = kakaomap_mcp_client
        self.tool_name = tool_name

    def estimate_eta_stats(
        self,
        participants: List[Participant],
        candidate: MeetingCandidate,
    ) -> EtaStats:
        etas: List[float] = []
        for p in participants:
            if not getattr(p, "home_anchor", None):
                continue

            origin = p.home_anchor
            # destination은 place_name or address 로 주는 게 자연스럽다
            # (필요하면 "역삼AA이자카야 서울 강남구 테헤란로 456" 같이 합쳐도 됨)
            destination = candidate.place_name

            arguments: Dict[str, Any] = {
                "origin": origin,           # ✅ inputSchema 기준
                "destination": destination  # ✅ inputSchema 기준
            }

            print("[ETA] calling KakaoMap-GetPublicTransitDirections with:",
                  json.dumps(arguments, ensure_ascii=False))

            try:
                resp = self.client.call(
                    "tools/call",
                    {
                        "name": self.tool_name,
                        "arguments": arguments,
                    },
                )
                print("[ETA] MCP raw resp for", origin, "->", destination, ":",
                      json.dumps(resp, indent=2, ensure_ascii=False))
            except Exception as e:
                print("[ETA] MCP call error for", origin, "->", destination, ":", repr(e))
                continue

            duration_min = self._extract_duration_minutes(resp)
            if duration_min is not None:
                etas.append(float(duration_min))

        if not etas:
            print("[ETA] no valid ETA values -> return empty EtaStats")
            return EtaStats(avg=None, max=None, std=None)

        avg = sum(etas) / len(etas)
        mx = max(etas)
        var = sum((e - avg) ** 2 for e in etas) / len(etas)
        std = var ** 0.5

        stats = EtaStats(avg=int(round(avg)), max=int(round(mx)), std=std)
        print("[ETA] final EtaStats:", stats)
        return stats


    def _extract_duration_minutes(self, resp: Dict[str, Any]) -> float | None:
        """
        KakaoMap-GetPublicTransitDirections 응답에서 '소요시간: XX분'을 파싱해서
        분 단위(float)로 반환한다.
        """
        result = resp.get("result") if isinstance(resp, dict) else None
        if not isinstance(result, dict):
            return None

        content = result.get("content")
        if not isinstance(content, list):
            return None

        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "text":
                continue
            text = item.get("text")
            if not isinstance(text, str):
                continue

            # 예: "소요시간: 40분" / "소요시간 : 35분"
            m = re.search(r"소요시간\s*:\s*([0-9]+)\s*분", text)
            if m:
                try:
                    minutes = float(m.group(1))
                    return minutes
                except ValueError:
                    continue

        return None