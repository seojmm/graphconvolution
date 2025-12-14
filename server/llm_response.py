import logging
import os
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(".env.local")

logger = logging.getLogger(__name__)


class LLMResponse:
    """
    Thin wrapper around the Kanana API client.

    Defaults to the Kanana-2-30b base model but allows override via env or ctor.
    """

    def __init__(self, model: Optional[str] = None):
        self.kanana_api_key = os.getenv("KANANA_API_KEY")
        self.kanana_base_url = os.getenv("KANANA_BASE_URL")

        if not self.kanana_api_key:
            logger.warning("KANANA_API_KEY is not configured. LLM calls will fail.")

        if not self.kanana_base_url:
            logger.warning("KANANA_BASE_URL is not configured. Using default OpenAI base URL.")

        self.client = OpenAI(
            base_url=self.kanana_base_url or None,
            api_key=self.kanana_api_key,
        )

    def _system_prompt(self) -> str:
        return (
            "당신은 카카오에서 개발된 언어모델 카나나(Kanana)입니다. "
        )

    def get_response(self, prompt: str, temperature: float = 0) -> str:
        if not self.kanana_api_key:
            raise ValueError("KANANA_API_KEY is not configured.")

        logger.info(
            "LLM request start",
            extra={"prompt_len": len(prompt), "model": self.client.models.list().data[0].id},
        )

        try:
            response = self.client.chat.completions.create(
                model=self.client.models.list().data[0].id,
                messages=[
                    {
                        "role": "system",
                        "content": self._system_prompt(),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
            )
            content = response.choices[0].message.content or "{}"
            return content
        except Exception:
            logger.exception("LLM request failed")
            return "{}"  # 실패 시 빈 JSON 반환

# if __name__ == "__main__":
#     llm = LLMResponse()
#     print(llm.client.models.list().data[0].id)
#     # test_prompt = "장소: 카페베네 / 주소: 서울특별시 강남구 테헤란로 123"
#     # result = llm.get_response(test_prompt)
#     # print("LLM Response:", result)