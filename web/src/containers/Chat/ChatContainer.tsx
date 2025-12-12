"use client";

import { FormEvent, useState } from "react";

type Message = { role: "user" | "assistant"; content: string };

// If NEXT_PUBLIC_API_BASE_URL is unset, use same-origin (relative path) to avoid CORS issues.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "";
const SUGGESTIONS = [
  "주차 가능한 홍대 카페 추천해줘",
  "강남에서 데이트하기 좋은 식당 알려줘",
  "오늘 날씨 어때?",
  "영업시간·휴무일·주차 정보 모두 알려줘",
];

const ChatContainer = ({ label = "채팅" }: { label?: string }) => {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: "무엇이든 물어보세요. 장소 정보도 챗봇처럼 답변해 드릴게요." },
  ]);
  const [loading, setLoading] = useState(false);

  const sendMessage = async (query: string) => {
    setMessages((prev) => [...prev, { role: "user", content: query }]);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/extract?query=${encodeURIComponent(query)}`);
      if (!res.ok) throw new Error(`요청 실패: ${res.status}`);
      const data = await res.json();
      const reply =
        typeof data?.llmResult === "string"
          ? data.llmResult
          : JSON.stringify(data?.llmResult ?? data, null, 2);
      setMessages((prev) => [...prev, { role: "assistant", content: reply }]);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "요청 중 오류가 발생했습니다.";
      setMessages((prev) => [...prev, { role: "assistant", content: `에러: ${message}` }]);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const query = input.trim();
    if (!query || loading) return;
    await sendMessage(query);
  };

  const handleSuggestion = (text: string) => {
    if (loading) return;
    void sendMessage(text);
  };

  return (
    <div className="flex h-full flex-col bg-white text-[#1f1f1f] pb-16">
      <header className="border-b px-4 py-3 font-semibold">{label}</header>

      <div className="flex flex-1 flex-col gap-3 overflow-y-auto px-4 py-3">
        {messages.map((msg, idx) => (
          <div
            key={`${msg.role}-${idx}`}
            className={`max-w-[80%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
              msg.role === "user"
                ? "self-end bg-[#ffeb3b] text-[#1f1f1f]"
                : "self-start bg-gray-100 text-gray-800"
            }`}
          >
            <div className="mb-1 text-[11px] uppercase tracking-wide text-gray-500">
              {msg.role === "user" ? "You" : "Server"}
            </div>
            {msg.content}
          </div>
        ))}
        {loading && <div className="text-xs text-gray-500">요청 중...</div>}

        <div className="mt-2 flex flex-wrap gap-2">
          {SUGGESTIONS.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => handleSuggestion(item)}
              disabled={loading}
              className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs text-gray-700 hover:bg-gray-100 disabled:opacity-50"
            >
              {item}
            </button>
          ))}
        </div>
      </div>

      <form onSubmit={handleSubmit} className="flex items-center gap-2 border-t px-4 py-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="쿼리를 입력하세요"
          className="flex-1 rounded-md border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#ffeb3b]"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="rounded-md bg-[#ffeb3b] px-4 py-2 text-sm font-semibold text-[#1f1f1f] shadow disabled:opacity-50"
        >
          {loading ? "전송 중..." : "전송"}
        </button>
      </form>
    </div>
  );
};

export default ChatContainer;
