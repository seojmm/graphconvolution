import html
import logging
import os
import re
from typing import Dict, List, Tuple

import requests
from models import DaumBlogResult, DaumCafeResult, DaumWebResult

logger = logging.getLogger(__name__)


class DaumSearchTool:
    """Lightweight Daum search helper for web/blog/cafe."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("KAKAO_REST_API_KEY")
        if not self.api_key:
            raise ValueError("KAKAO_REST_API_KEY is not configured.")

    def _request(self, path: str, params: dict) -> dict:
        url = f"https://dapi.kakao.com{path}"
        headers = {"Authorization": f"KakaoAK {self.api_key}"}
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _clean(self, text: str) -> str:
        no_tags = re.sub(r"<[^>]+>", " ", text or "")
        return re.sub(r"\s+", " ", html.unescape(no_tags)).strip()

    def collect_contents(self, query: str, sort: str = "recency", page: int = 1, size: int = 5) -> Tuple[str, Dict]:
        """Search Daum sources and return concatenated clean text plus source counts."""
        params = {"query": query, "sort": sort, "page": page, "size": size}
        web = self._request("/v2/search/web", params)
        blog = self._request("/v2/search/blog", params)
        cafe = self._request("/v2/search/cafe", params)

        def _extract(dataset: dict) -> List[str]:
            results = []
            for doc in dataset.get("documents", []):
                title = self._clean(doc.get("title", ""))
                body = self._clean(doc.get("contents", ""))
                combined = f"{title}\n{body}".strip()
                if combined:
                    results.append(combined)
            return results

        contents: List[str] = _extract(web) + _extract(blog) + _extract(cafe)
        combined = "\n\n".join(contents).strip()
        source_counts = {
            "web": len(web.get("documents", [])),
            "blog": len(blog.get("documents", [])),
            "cafe": len(cafe.get("documents", [])),
        }
        return combined, source_counts

    def search_all(self, query: str, sort: str = "accuracy", page: int = 1, size: int = 5) -> Dict[str, Dict]:
        """Return raw Daum search payloads for web/blog/cafe."""
        params = {"query": query, "sort": sort, "page": page, "size": size}
        return {
            "web": self._request("/v2/search/web", params),
            "blog": self._request("/v2/search/blog", params),
            "cafe": self._request("/v2/search/cafe", params),
        }

