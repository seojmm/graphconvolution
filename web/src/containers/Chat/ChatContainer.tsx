"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

type Message = { role: "user" | "assistant"; content: string; meta?: string; isLoading?: boolean };

// 기본 API 엔드포인트: 로컬 FastAPI. 필요 시 NEXT_PUBLIC_API_BASE_URL로 재정의.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const tryParseJson = (text: string): unknown => {
  const trimmed = (text || "").trim();
  if (!trimmed) return null;
  const withoutFences = trimmed.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/i, "");
  try {
    return JSON.parse(withoutFences);
  } catch {
    return null;
  }
};

const normalizeSuggestionTemplates = (items: unknown): string[] => {
  if (!Array.isArray(items)) return [];
  return items
    .filter((item): item is string => typeof item === "string")
    .map((item) => item.trim())
    .filter(Boolean);
};

const asRecord = (value: unknown): Record<string, unknown> | null => {
  if (!value || typeof value !== "object") return null;
  return value as Record<string, unknown>;
};

const ChatContainer = ({ label = "채팅" }: { label?: string }) => {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: "무엇이든 물어보세요. LLM이 바로 답변합니다." },
  ]);
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [expandedMeta, setExpandedMeta] = useState<Set<number>>(new Set());
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const conversationIdRef = useRef<string>(
    globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`,
  );

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const toggleMeta = (idx: number) => {
    setExpandedMeta((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const sendMessage = async (query: string) => {
    const historyForRequest = [...messages, { role: "user" as const, content: query }].filter(
      (msg) => !msg.isLoading,
    );

    setInput("");
    setLoading(true);
    setSuggestions([]);
    setMessages((prev) => [
      ...prev,
      { role: "user", content: query },
      { role: "assistant", content: "", isLoading: true },
    ]);

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: "agent",
          message: query,
          conversationId: conversationIdRef.current,
          history: historyForRequest.map((msg) => ({ role: msg.role, content: msg.content, meta: msg.meta })),
        }),
      });
      if (!res.ok) throw new Error(`요청 실패: ${res.status}`);
      const data = await res.json();
      const reply =
        typeof data?.reply === "string" ? data.reply : JSON.stringify(data?.reply ?? data, null, 2);
      const intent = typeof data?.intent === "string" ? data.intent : "";

      const metaParts: string[] = [];
      if (intent) metaParts.push(`intent: ${intent}`);
      const metaObj = data?.meta;
      if (metaObj?.attempts) metaParts.push(`attempts: ${metaObj.attempts}`);
      if (Array.isArray(metaObj?.extraQueries) && metaObj.extraQueries.length) {
        metaParts.push(`tools: web_search -> ${metaObj.extraQueries.join(" | ")}`);
      }
      if (metaObj?.sourceCounts && typeof metaObj.sourceCounts === "object") {
        metaParts.push(`sourceCounts: ${JSON.stringify(metaObj.sourceCounts)}`);
      }
      if (metaObj?.reason) metaParts.push(`reason: ${metaObj.reason}`);
      if (Array.isArray(metaObj?.steps) && metaObj.steps.length) {
        metaParts.push(`steps: ${metaObj.steps.join(" > ")}`);
      }
      const meta = metaParts.join("\n");

      const explicitSuggestionsTop = normalizeSuggestionTemplates(data?.suggestions);
      const explicitSuggestionsMeta = normalizeSuggestionTemplates(metaObj?.suggestions);
      const agentObj = asRecord(data?.agent);
      const explicitSuggestionsAgent = normalizeSuggestionTemplates(agentObj?.suggestions);
      const explicitSuggestions = explicitSuggestionsTop.length
        ? explicitSuggestionsTop
        : explicitSuggestionsAgent.length
          ? explicitSuggestionsAgent
          : explicitSuggestionsMeta;

      if (explicitSuggestions.length) {
        setSuggestions(explicitSuggestions);
      } else {
        const parsed = asRecord(tryParseJson(reply));
        const missingInfoRaw =
          parsed?.missing_info ?? parsed?.missingInfo ?? parsed?.missing_fields ?? parsed?.missingFields;
        const missingInfo = normalizeSuggestionTemplates(missingInfoRaw);
        setSuggestions(missingInfo);
      }

      setMessages((prev) => {
        const next = [...prev];
        for (let i = next.length - 1; i >= 0; i--) {
          if (next[i].role === "assistant" && next[i].isLoading) {
            next[i] = { role: "assistant", content: reply || "(응답 없음)", meta: meta || undefined };
            return next;
          }
        }
        return [...next, { role: "assistant", content: reply || "(응답 없음)", meta: meta || undefined }];
      });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "요청 중 오류가 발생했습니다.";
      setSuggestions([]);
      setMessages((prev) => {
        const next = [...prev];
        for (let i = next.length - 1; i >= 0; i--) {
          if (next[i].role === "assistant" && next[i].isLoading) {
            next[i] = { role: "assistant", content: `에러: ${message}` };
            return next;
          }
        }
        return [...next, { role: "assistant", content: `에러: ${message}` }];
      });
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
    setInput(text);
    inputRef.current?.focus();
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
              {msg.role === "user" ? "You" : "LLM"}
            </div>
            {msg.isLoading ? (
              <div className="flex items-center gap-2 text-xs">
                <span className="animate-pulse rounded-full bg-[#ffeb3b] px-2 py-1 text-[11px] font-semibold text-[#1f1f1f]">
                  Thinking
                </span>
                <span className="text-gray-500">추론 중...</span>
              </div>
            ) : (
              msg.content
            )}
            {msg.meta && (
              <div className="mt-2 border-t pt-1 text-[11px] text-gray-500">
                <button
                  type="button"
                  onClick={() => toggleMeta(idx)}
                  className="underline text-[#1f1f1f]"
                >
                  {expandedMeta.has(idx) ? "접기" : "Working"}
                </button>
                {expandedMeta.has(idx) ? (
                  <pre className="mt-1 whitespace-pre-wrap">{msg.meta}</pre>
                ) : (
                  <div className="mt-1 truncate">{msg.meta}</div>
                )}
              </div>
            )}
          </div>
        ))}

        <div ref={bottomRef} />

        {!loading && suggestions.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
            {suggestions.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => handleSuggestion(item)}
                className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs text-gray-700 hover:bg-gray-100"
              >
                {item}
              </button>
            ))}
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="flex items-center gap-2 border-t px-4 py-3">
        <input
          ref={inputRef}
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
