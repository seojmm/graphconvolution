from ..Domain.model import MeetingCandidate, UserRequest, ScheduleResult
from ..ports.calender_gateway import CalenderGateway, KakaoMemoChatGateway, KakaoMapGateway
from typing import Optional, List, Dict, Any
from datetime import datetime
import re


#Action Agent (Execution)
#톡캘린더 MCP 일정 생성(CreateEvent, 중복 확인(GetEvent))

# ToDo 나중에 필요하면 중복 일정 체크/권한 검사 등의 비즈니스 로직 추가
class ActionAgent:
    """선택된 후보를 실제 캘린더 이벤트로 만드는 에이전트."""

    def __init__(
        self,
        calender_gateway: CalenderGateway,
        memo_gateway: Optional[KakaoMemoChatGateway] = None,
        map_gateway: Optional[KakaoMapGateway] = None,
    ):
        self.calender_gateway = calender_gateway
        self.memo_gateway = memo_gateway
        self.map_gateway = map_gateway


    def schedule_meeting(self, user_request, selected_candidate):
        schedule_result = self.calender_gateway.create_event(
            user_request=user_request,
            candidate=selected_candidate,
            attendees=[p.participant_id for p in user_request.participants],
        )
        # 부가 작업: 이동 경로 조회 + 메모챗 알림
        routes: List[str] = []
        place_info_text = None
        if self.map_gateway:
            # 장소 검색(카카오맵)
            try:
                place_resp = self.map_gateway.search_place(selected_candidate.place_name)
                place_info_text = self._format_place_info(
                    place_resp,
                    fallback_name=selected_candidate.place_name,
                    fallback_address=selected_candidate.address,
                )
            except Exception:
                place_info_text = None
            destination = selected_candidate.address or selected_candidate.place_name
            for p in user_request.participants:
                if not getattr(p, "home_anchor", None):
                    continue
                try:
                    resp = self.map_gateway.get_transit_directions(p.home_anchor, destination)
                    # MCP 응답에서 사람 읽기 좋은 텍스트만 뽑아낸다.
                    route_text = self._extract_text_content(resp)
                    routes.append(self._format_route_entry(p, route_text))
                except Exception as exc:  # 경로 조회 실패는 무시
                    routes.append(f"- {p.name or p.participant_id} 경로 조회 실패: {exc}")

        if self.memo_gateway:
            lines = [
                "[일정 등록 완료]",
                f"제목: {selected_candidate.place_name}",
                f"시작 시간: {self._format_time(selected_candidate.start_time)}",
                f"종료 시간: {self._format_time(selected_candidate.end_time)}",
                f"장소: {selected_candidate.place_name}",
                f"주소: {selected_candidate.address}",
            ]
            if place_info_text:
                lines.append(f"{place_info_text}")
            if routes:
                lines.append("")
                lines.append("[이동 경로]")
                # 참가자별 경로 사이에 빈 줄을 넣어 가독성 확보
                for idx, r in enumerate(routes):
                    lines.append(r)
                    if idx < len(routes) - 1:
                        lines.append("")
            try:
                self.memo_gateway.send_message("\n".join(lines))
            except Exception:
                pass  # 메모챗 실패는 일정 생성에는 영향 없음

        return schedule_result

    @staticmethod
    def _extract_text_content(resp: Dict[str, Any]) -> str:
        """
        MCP tools/call 응답에서 content[].text를 우선 추출해 사람이 읽기 쉽게 반환.
        """
        if not isinstance(resp, dict):
            return str(resp)
        body = resp.get("result") if "result" in resp else resp
        if isinstance(body, dict):
            content = body.get("content")
            if isinstance(content, list) and content:
                first = content[0]
                if isinstance(first, dict) and first.get("type") == "text":
                    return first.get("text", "").strip()
        return str(resp)

    @staticmethod
    def _format_route_entry(participant, route_text: str) -> str:
        """
        경로 안내 텍스트를 참가자/출발지와 함께 보기 좋게 포맷.
        긴 링크로 인해 잘리는 것을 줄이기 위해 요약하고, 링크는 한 줄로 별도 표기.
        """
        link = None
        lines = []
        for line in route_text.splitlines():
            if "http" in line:
                m = re.search(r"(https?://[^\)\s]+)", line)
                if m:
                    link = m.group(1)
                continue
            if "상세 경로" in line:
                continue
            if line.strip():
                lines.append(line.strip())
        cleaned = "\n".join(lines).strip()
        header = f"- {getattr(participant, 'name', None) or participant.participant_id} ({getattr(participant, 'home_anchor', '')})"
        if link:
            cleaned = f"{cleaned}\n상세 경로: {link}".strip()
        return f"{header}\n{cleaned}" if cleaned else header

    @staticmethod
    def _format_time(value: str) -> str:
        """
        ISO 문자열(YYYY-MM-DDThh:mm:ss[+offset])을 사람이 읽기 쉬운 형식으로 변환.
        예: 2025년 12월 10일 (수) 오후 6시 00분
        """
        try:
            dt = datetime.fromisoformat(value)
        except Exception:
            return value  # 파싱 실패 시 원문 반환
        weekday = "월화수목금토일"[dt.weekday()]
        meridiem = "오전" if dt.hour < 12 else "오후"
        hour_12 = dt.hour if 1 <= dt.hour <= 12 else (dt.hour - 12 if dt.hour > 12 else 12)
        return f"{dt.year}년 {dt.month}월 {dt.day}일 ({weekday}) {meridiem} {hour_12}시 {dt.minute:02d}분"

    @staticmethod
    def _format_place_info(resp: Dict[str, Any], fallback_name: str, fallback_address: str) -> Optional[str]:
        """
        장소 검색 결과에서 첫 번째 place 정보를 요약해 반환.
        """
        text = ActionAgent._extract_text_content(resp)
        if not text:
            # 검색 실패 시 fallback
            return None
        # 간단 요약: 첫 번째 줄과 주소/링크만 남기기
        link = None
        addr = None
        lines = []
        for line in text.splitlines():
            if "주소" in line and addr is None:
                addr = line.replace("주소:", "").strip(" -")
                continue
            if "http" in line and link is None:
                m = re.search(r"(https?://[^\)\s]+)", line)
                if m:
                    link = m.group(1)
                continue
            if line.strip():
                lines.append(line.strip())
        parts = []
        # 주소가 fallback과 같으면 중복 출력 방지
        if addr and addr != fallback_address:
            parts.append(addr)
        if link:
            parts.append(f"자세히 보기: {link}")
        # if nothing parsed, fallback을 쓰지 않음(이미 상단에 표시되므로)
        if not parts and text:
            parts.append(text)
        return " / ".join(parts) if parts else None
