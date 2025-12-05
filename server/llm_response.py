import logging
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(".env.local")

logger = logging.getLogger(__name__)


class LLMResponse:
    def __init__(self):
        self.kanana_api_key = os.getenv("KANANA_API_KEY")
        self.kanana_base_url = os.getenv("KANANA_BASE_URL")
        self.model_id = os.getenv("KANANA_MODEL_ID")  # 선택: 고정 모델 지정

        if not self.kanana_api_key:
            logger.warning("KANANA_API_KEY is not configured. LLM calls will fail.")

        if not self.kanana_base_url:
            logger.warning("KANANA_BASE_URL is not configured. Using default OpenAI base URL.")

        self.client = OpenAI(
            base_url=self.kanana_base_url or None,
            api_key=self.kanana_api_key,
        )

        # 모델 ID 미지정 시, 초기화 시점에 한 번만 조회
        if self.kanana_api_key and not self.model_id:
            try:
                models = self.client.models.list()
                if models.data:
                    self.model_id = models.data[0].id
                    logger.info("Discovered Kanana model", extra={"model": self.model_id})
                else:
                    logger.error("No models returned from Kanana backend.")
            except Exception:
                logger.exception("Failed to list models from Kanana backend.")
                self.model_id = None

    def get_response(self, prompt: str) -> str:
        if not self.kanana_api_key:
            raise ValueError("KANANA_API_KEY is not configured.")

        if not self.model_id:
            raise ValueError("KANANA_MODEL_ID is not configured and automatic discovery failed.")

        logger.info(
            "LLM request start",
            extra={"prompt_len": len(prompt), "model": self.model_id},
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "당신은 카카오(kakao)에서 개발된 친절한 인공지능 언어모델이고 이름은 카나나(kanana)입니다. "
                            "2024년 7월 이후 사건에 대한 정보는 알 수 없다고 답해야합니다. "
                            "현재 시간, 날짜, 사건 등 외부 정보를 참조해야 답할 수 있는 질문에는 외부 검색을 사용하라고 추천하세요. "
                            "URL에 기반한 사용자 질의의 경우 사용자에게 URL에 있는 정보를 직접 입력하도록 요청합니다. "
                            "카나나(kanana)의 모델 사이즈나 파라미터 정보는 비공개입니다."
                        ),
                    },
                    {
                        "role": "system",
                        "content": (
                            "너는 간결하게 한국어로만 답변한다. 프롬프트가 JSON을 요청하면 JSON만 반환하고 추가 설명은 하지 마."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
            )
        except Exception:
            logger.exception("LLM request failed")
            raise

        content = response.choices[0].message.content
        logger.info("LLM response received", extra={"response_len": len(content)})
        return content
