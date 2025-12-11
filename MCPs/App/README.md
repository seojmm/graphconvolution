
# 가정사항
입력:
## case 1 - 장소가 특정되어있을 때
UserRequest(user_query="이번 주 금요일 강남역 근처에서 점심을 12시쯤에 먹으려고 해! 여성 4명에서 갈 가성비 맛집 추천해줘!", ...)

## case 2 - 장소 특정 X
UserRequest(user_query="12월 20일 저녁 6시에 회식할건데. 총 3명에서 만날 예정이고, 각자 건대입구역, 홍대입구역, 서울대입구역에서 출발할 거야. 회식비는 총 12만원 내외로 사용 가능하고, 한식은 제외해줘.", ...)


# 설계 내용
- 각 에이전트의 역할/입출력,
- DB/캘린더/지도와의 경계(Port),
- Orchestrator의 흐름

# 나중에 해야 할 일(1,3번은 일단 더미 설계만 되어있고 나중에 Kanana,지도,캘린더 API 붙여서 작동되게 만들면 됨!)
  1. LLM-based(kanana) ConstraintExtraction 구현(extract_with_llm)
  2. MeetingRepository 실제 구현(Neo4j + GraphRAG)
  3. EtaService, CalenderGateway 실제 구현
  4. FastAPI toy 서버 따로 파서 프론트에서 직접 하거나, 데모 버전 보여줘야하는건가?

# 흐름:
  1. Orchestrator.plan()
    - ConstraintExtractionAgent.extract()
      → 자연어 → Constraints JSON 구조

  2. KnowledgeAgent.propose_candidates(constraints)
    - 내부에서 MeetingRepository.search_candidates(constraints) 호출
    - 지금은 InMemoryMeetingRepository가 dummy 후보를 반환
    - 나중에는 Neo4jMeetingRepository가
        Text-to-Cypher / GraphRAG / Filtering 로직으로 후보 생성

  3. VerificationAgent.evaluate(constraints, candidates, participants)
    - EtaService.estimate_eta_stats() 호출 → ETA 통계
    - fairness_score, satisfaction_score, reasoning 채우기

  4. OrchestratorResult로 묶어서 /orchestrate 응답

  5. 프론트에서 후보 중 하나를 선택하면 /schedule 호출
    - ActionAgent.schedule_meeting() → CalenderGateway.create_event() 호출
    - 나중에는 실제 톡캘린더/내부 캘린더 API를 여기서 사용



# DB팀 할 일
- MeetingRepository 구현체 하나 만드는 것.

# 설계 예시
- ports/meeting_repository_neo4j.py


# schedule 예시
'''
{
  "user_request": {
    "user_query": "12월 10일 오후 6시에 강남에서 모임 잡아줘",
    "user_id": "user-123",
    "participants": [
      { "participant_id": "user1", "name": "Alice", "home_anchor": "건대입구역" },
      { "participant_id": "user2", "name": "Bob", "home_anchor": "서울대입구역" }
    ]
  },
  "selected_candidate": {
    "id": "cand-1",
    "request_id": "req-1",
    "place_name": "가츠시 건대점",
    "place_id": "place-123",
    "address": "서울 광진구 광나루로 418",
    "start_time": "2025-12-10T18:00:00",
    "end_time": "2025-12-10T19:00:00",
    "reasoning": ""
  }
}
'''