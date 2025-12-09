from ..Domain.model import MeetingCandidate, UserRequest, ScheduleResult
from ..ports.calender_gateway import CalenderGateway, KakaoMemoChatGateway, KakaoMapGateway
from typing import Optional, List, Dict, Any
from datetime import datetime
import re

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate


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
        llm: Optional[BaseChatModel] = None,
    ):
        self.calender_gateway = calender_gateway
        self.memo_gateway = memo_gateway
        self.map_gateway = map_gateway
        self.llm = llm


    def schedule_meeting(self, user_request, selected_candidate):
        schedule_result = self.calender_gateway.create_event(
            user_request=user_request,
            candidate=selected_candidate,
            attendees=[p.participant_id for p in user_request.participants],
        )
        # 부가 작업: 이동 경로 조회 + 메모챗 알림
        routes: List[str] = []
        place_info_text = None
        memo_text: Optional[str] = None
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
            # 요청에 따라 LLM이 연결되어 있어도 기존 포맷을 사용한다.
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
            memo_text = "\n".join(lines)
            try:
                self.memo_gateway.send_message(memo_text)
                schedule_result.memo_chat_sent = True
                schedule_result.memo_chat_message = memo_text
            except Exception:
                schedule_result.memo_chat_sent = False

        # 사용자에게 보여줄 최종 안내문(LLM 사용, 실패 시 memo_text로 폴백)
        user_summary: Optional[str] = None
        if self.llm:
            try:
                user_summary = self._render_llm_summary(
                    candidate=selected_candidate,
                    place_info_text=place_info_text,
                    routes=routes,
                )
            except Exception:
                user_summary = None
        if not user_summary:
            user_summary = memo_text
        schedule_result.user_summary = user_summary

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

    def _render_llm_summary(
        self,
        candidate: MeetingCandidate,
        place_info_text: Optional[str],
        routes: List[str],
    ) -> str:
        """LLM으로 최종 안내 문구를 포맷한다."""
        prompt = ChatPromptTemplate.from_template(
            """다음 정보를 바탕으로 최종 안내문을 만들어 주세요.
- 문장은 반드시 "선택하신 약속에 대해서 정리해드릴게요~" 로 시작.
- 톤: 한국어 존댓말, 친구에게 알려주는 말투. 군더더기/중복 문구 금지.
- 형식: 짧은 한두 문장 + 불릿 3~6줄. 이모지·장식 금지.
- 필수: 제목, 시작/종료 시각(사람이 읽기 쉬운 형식), 장소 이름, 주소.
- 장소 정보(place_info_text)는 가능하면 주소 문장 뒤에 바로 이어서 포함해 주세요(예: "장소는 ○○에 위치해 있습니다. 자세히 보기: 링크").
- 선택: 장소 추가 정보(place_info_text), 이동 경로(routes). 경로가 여러 개면 사람별로 줄바꿈.
- 링크는 그대로 노출하되 문장형으로 풀어쓰지 말 것.

입력:
- 제목: {title}
- 시작: {start_text}
- 종료: {end_text}
- 장소: {place_name}
- 주소: {address}
- 장소 정보: {place_info_text}
- 이동 경로:
{routes_block}

출력: 위 조건을 만족하는 한국어 안내문 한 덩어리만."""
        )
        routes_block = "\n".join(routes) if routes else "없음"
        start_text = self._format_time(candidate.start_time)
        end_text = self._format_time(candidate.end_time)
        messages = prompt.format_messages(
            title=candidate.place_name,
            start_text=start_text,
            end_text=end_text,
            place_name=candidate.place_name,
            address=candidate.address or "",
            place_info_text=place_info_text or "없음",
            routes_block=routes_block,
        )
        resp = self.llm.invoke(messages)
        text = resp.content if hasattr(resp, "content") else str(resp)
        return text.strip()

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
