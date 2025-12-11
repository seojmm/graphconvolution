# server/extraction_service.py
import asyncio
import json
import logging
import re
import html
from typing import Dict, Any, List

# 기존 코드에 있는 의존성들 (경로는 프로젝트 구조에 맞게 조정 필요)
from .llm_response import LLMResponse
from .kakao_data_collector import KakaoDataCollector
import httpx  # 비동기 HTTP 요청을 위해 requests 대신 httpx 사용 추천

logger = logging.getLogger(__name__)

class ExtractionService:
    def __init__(self):
        self.collector = KakaoDataCollector()
        self.llm_client = LLMResponse()
        self.kakao_api_key = self.collector.kakao_api_key

    async def _daum_search_async(self, client: httpx.AsyncClient, path: str, params: dict) -> dict:
        """Daum 검색 비동기 요청"""
        url = f"https://dapi.kakao.com{path}"
        headers = {"Authorization": f"KakaoAK {self.kakao_api_key}"}
        try:
            resp = await client.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"Daum API failed: {e}")
            return {}

    async def _collect_daum_contents(self, query: str) -> str:
        """웹/블로그/카페 검색 결과를 비동기로 한 번에 가져와 병합"""
        params = {"query": query, "sort": "recency", "page": 1, "size": 3}
        
        async with httpx.AsyncClient() as client:
            # 3개 검색 API를 동시에 호출 (Parallel execution)
            results = await asyncio.gather(
                self._daum_search_async(client, "/v2/search/web", params),
                self._daum_search_async(client, "/v2/search/blog", params),
                self._daum_search_async(client, "/v2/search/cafe", params),
            )
        
        web, blog, cafe = results
        combined_text = []
        
        # 간단한 정제 로직 (app.py 로직 재사용)
        def clean(text):
            return re.sub(r"<[^>]+>", " ", html.unescape(text or "")).strip()

        for res in [web, blog, cafe]:
            for doc in res.get("documents", []):
                title = clean(doc.get("title", ""))
                body = clean(doc.get("contents", ""))
                if title or body:
                    combined_text.append(f"{title}\n{body}")
        
        return "\n\n".join(combined_text)[:4000] # LLM 컨텍스트 제한 고려하여 자름

    async def extract_info(self, query: str) -> Dict[str, Any]:
        """최종 호출 함수: 검색 -> LLM 추출"""
        if not self.llm_client.kanana_api_key:
            logger.error("Kanana API Key missing")
            return {}

        combined_contents = await self._collect_daum_contents(query)
        if not combined_contents:
            return {}

        system_prompt = (
            "너는 장소 정보를 추출하는 도우미다. 주어진 텍스트에서 "
            "parking, breaktime, openingHours, closedDays, menus, notes 정보를 JSON으로만 추출해라."
        )
        prompt = f"{system_prompt}\n\n[텍스트]\n{combined_contents}\n\nJSON:"

        # LLM 호출 (run_in_threadpool 등을 사용하거나 비동기 지원 시 await)
        # 여기서는 동기 함수를 비동기로 감싸서 실행
        loop = asyncio.get_running_loop()
        try:
            response_text = await loop.run_in_executor(
                None, self.llm_client.get_response, prompt
            )
            # JSON 파싱 시도
            start = response_text.find('{')
            end = response_text.rfind('}') + 1
            if start != -1 and end != -1:
                 return json.loads(response_text[start:end])
            return {}
        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            return {}