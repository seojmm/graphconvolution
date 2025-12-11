import logging
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(".env.local")

logger = logging.getLogger(__name__)


class LLMResponse:
    def __init__(self, model: str):
        """
        model: "kanana-*" 계열이면 Kanana 설정을 사용, 그 외에는 OpenAI 설정을 사용.
        """
        model_lower = model.lower()
        if model_lower.startswith("kanana"):
            self.api_key = os.getenv("KANANA_API_KEY")
            self.base_url = os.getenv("KANANA_BASE_URL")
            # self.model_id = "kanana-2-30b"
            self.model_id = model
            if not self.api_key:
                raise ValueError("KANANA_API_KEY is not configured.")
        else:
            self.api_key = os.getenv("OPENAI_API_KEY")
            self.base_url = os.getenv("OPENAI_BASE_URL")
            self.model_id = model or os.getenv("OPENAI_MODEL_ID", "gpt-4o-mini")
            if not self.api_key:
                raise ValueError("OPENAI_API_KEY is not configured.")

        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)

    def get_response(self, prompt: str) -> str:
        logger.info(
            "LLM request start",
            extra={"prompt_len": len(prompt), "model": self.model_id},
        )

        try:
            if self.model_id.lower().startswith("kanana"):
                response = self.client.chat.completions.create(
                    model=self.client.models.list().data[0].id,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "당신은 카카오(kakao)에서 개발된 친절한 인공지능 언어모델이고 이름은 카나나(kanana)입니다. "
                                "주어진 텍스트 정보에서 사용자의 질문에 꼼꼼히 답변해야 합니다. "
                                "현재 시간, 날짜, 사건 등 외부 정보를 참조해야 답할 수 있는 질문에는 외부 검색을 사용하라고 추천하세요. "
                                "URL에 기반한 사용자 질의의 경우 사용자에게 URL에 있는 정보를 직접 입력하도록 요청합니다. "
                                "카나나(kanana)의 모델 사이즈나 파라미터 정보는 비공개입니다."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0,
                    max_tokens=512,
                )
            else:
                response = self.client.chat.completions.create(
                    model=self.model_id,
                    messages=[
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0,
                    max_tokens=256,
                )
        except Exception:
            logger.exception("LLM request failed")
            raise

        content = response.choices[0].message.content
        logger.info("LLM response received", extra={"response_len": len(content)})
        return content
