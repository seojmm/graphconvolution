import asyncio
import json
import logging
import re
import html
import httpx
from typing import Dict, Any

# 같은 폴더 내 모듈 import 처리
try:
    from llm_response import LLMResponse
    from kakao_data_collector import KakaoDataCollector
except ImportError:
    from .llm_response import LLMResponse
    from .kakao_data_collector import KakaoDataCollector

logger = logging.getLogger(__name__)

class ExtractionService:
    def __init__(self):
        self.collector = KakaoDataCollector()
        # 여기서 LLMResponse()를 호출할 때 인자를 주지 않습니다.
        self.llm_client = LLMResponse()
        self.kakao_api_key = self.collector.kakao_api_key

    async def _daum_search_async(self, client: httpx.AsyncClient, path: str, params: dict) -> dict:
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
        params = {"query": query, "sort": "recency", "page": 1, "size": 2}
        
        async with httpx.AsyncClient() as client:
            results = await asyncio.gather(
                self._daum_search_async(client, "/v2/search/web", params),
                self._daum_search_async(client, "/v2/search/blog", params),
                self._daum_search_async(client, "/v2/search/cafe", params),
            )
        
        combined_text = []
        def clean(text):
            return re.sub(r"<[^>]+>", " ", html.unescape(text or "")).strip()

        for res in results:
            for doc in res.get("documents", []):
                title = clean(doc.get("title", ""))
                body = clean(doc.get("contents", ""))
                if title or body:
                    combined_text.append(f"{title}\n{body}")
        
        return "\n\n".join(combined_text)[:3500]

    async def extract_info(self, query: str) -> Dict[str, Any]:
        """검색 후 LLM을 통해 정보 추출"""
        if not self.llm_client.kanana_api_key:
            return {}

        combined_contents = await self._collect_daum_contents(query)
        if not combined_contents:
            return {}

        prompt = (
            f"[쿼리]\n{query}\n\n"
            f"[연결된 contents]\n{combined_contents}\n\n"
            "위 내용 중 쿼리와 동일한 장소에 관한 정보만 추출해서 JSON 형식으로 반환해."
            # "항상 JSON 하나만 간결하게 반환합니다. "
            # "사용자 메시지는 장소에 대한 검색 결과 텍스트이며 HTML 태그는 제거되어 있습니다. "
            # "쿼리에 포함된 상호/주소와 직접 관련 없는 정보는 무시합니다. "
            # "반드시 parking, breaktime, openingHours, closedDays, priceRange, menus, notes 키를 포함해 문자열로 채우고 "
            # "정보가 없으면 빈 문자열을 넣습니다. 필요 시 유용한 추가 키를 더해도 되지만 JSON 외의 텍스트는 금지합니다."
        )

        # 동기 함수인 get_response를 비동기 루프에서 실행
        loop = asyncio.get_running_loop()
        try:
            response_text = await loop.run_in_executor(
                None, self.llm_client.get_response, prompt
            )
            # JSON 파싱
            match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if match:
                return json.loads(match.group())
            return {}
        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            return {}