# Kakao/Daum FastAPI Service

## 구성
- `app.py`: FastAPI 엔드포인트 (/health, /regions, /places, /kakao/*, /daum/*, /extract, /chat, /kanana/qa, /orchestrate, /schedule).
- `kakao_data_collector.py`: Kakao 로컬 검색 수집기.
- `models.py`: Pydantic 응답 모델.
- `llm_response.py`: Kanana LLM 클라이언트 (/extract에서 사용).
- `graphiti_agent.py`: 서울/용산구/일식 상위 10개를 Graphiti에 적재하는 스크립트.
- `main.py`: 로컬 실행 엔트리포인트 (`uvicorn app:app --reload`).

## 환경변수 (.env.local)
- `KAKAO_REST_API_KEY` (필수)
- `KANANA_API_KEY` (필수, /extract)
- `OPENAI_API_KEY`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` (Graphiti 사용 시)

## 실행
- API 서버: `uv run uvicorn server.app:app --reload --env-file .env.local`
- Graphiti 적재: `uv run python server/graphiti_agent.py`
