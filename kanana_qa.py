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


        self.client = OpenAI(
            base_url=self.kanana_base_url or None,
            api_key=self.kanana_api_key,
        )

    def get_response(self, prompt: str) -> str:

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

if __name__ == "__main__":
    llm = LLMResponse()
    prompt = "너는 여러 조건을 고려하여 최적의 약속 장소(식당) 제공하는 인공지능 언어모델이야. 인사말을 짧게 해줘."
    answer = llm.get_response(prompt)
    print("LLM 답변:", answer)