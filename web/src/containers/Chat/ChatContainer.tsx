"use client";

import Image from "next/image";
import { FormEvent, useEffect, useRef, useState } from "react";
import Total10, { type PlaceInfo } from "@/components/Total10/Total10";

type Message = {
  role: "user" | "assistant";
  content: string;
  meta?: string;
  isLoading?: boolean;
  variant?: "timeQuestion" | "totalResults" | "bookingConfirm" | "bookingSummary" | "retryPrompt";
  choices?: string[];
  place?: PlaceInfo;
  detailUrl?: string;
};

type ScenarioStep = "idle" | "awaitingFollowup" | "awaitingTime" | "resultsShown";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const MEETING_DATE_LABEL = "2025년 12월 19일 (금)";
const DEFAULT_MEETING_MINUTES = 60;
const DEFAULT_MEETING_START = "12:00";
const PLACE_DETAIL_URL = "https://place.map.kakao.com/27504286";

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

const addMinutesToTime = (time: string, minutes: number): string => {
  const [hours, mins] = time.split(":").map((value) => parseInt(value, 10));
  if (Number.isNaN(hours) || Number.isNaN(mins)) return time;
  const date = new Date();
  date.setHours(hours, mins, 0, 0);
  date.setMinutes(date.getMinutes() + minutes);
  const hh = date.getHours().toString().padStart(2, "0");
  const mm = date.getMinutes().toString().padStart(2, "0");
  return `${hh}:${mm}`;
};

const formatKoreanTime = (time: string): string => {
  const [hours, mins] = time.split(":").map((value) => parseInt(value, 10));
  if (Number.isNaN(hours) || Number.isNaN(mins)) return time;
  const period = hours >= 12 ? "오후" : "오전";
  const hour12 = hours % 12 === 0 ? 12 : hours % 12;
  return `${period} ${hour12}시 ${mins.toString().padStart(2, "0")}분`;
};

const ChatContainer = ({ label = "채팅" }: { label?: string }) => {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: "안녕하세요. 오늘은 어떤 약속을 계획하고 싶으신가요?" },
  ]);
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [scenarioStep, setScenarioStep] = useState<ScenarioStep>("idle");
  const [selectedTime, setSelectedTime] = useState<string | null>(null);
  const [expandedMeta, setExpandedMeta] = useState<Set<number>>(new Set());
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const pendingThinkingTimers = useRef<number[]>([]);
  const conversationIdRef = useRef<string>(
    globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`,
  );

  const scrollToBottom = (behavior: ScrollBehavior = "smooth") => {
    const container = scrollContainerRef.current;
    if (!container) return;
    container.scrollTo({ top: container.scrollHeight, behavior });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    return () => {
      pendingThinkingTimers.current.forEach((id) => clearTimeout(id));
      pendingThinkingTimers.current = [];
    };
  }, []);

  const toggleMeta = (idx: number) => {
    setExpandedMeta((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const respondWithThinking = (
    message: Omit<Message, "role" | "isLoading"> & { delay?: number },
  ): void => {
    const { delay = 600, ...rest } = message;
    setMessages((prev) => [...prev, { role: "assistant", content: "", isLoading: true }]);
    const timerId = window.setTimeout(() => {
      setMessages((prev) => {
        const next = [...prev];
        for (let i = next.length - 1; i >= 0; i--) {
          if (next[i].role === "assistant" && next[i].isLoading) {
            next[i] = { role: "assistant", ...rest };
            break;
          }
        }
        return next;
      });
      pendingThinkingTimers.current = pendingThinkingTimers.current.filter((id) => id !== timerId);
    }, delay);
    pendingThinkingTimers.current.push(timerId);
  };

  const handleTimeSelection = (time: string, options?: { skipUserMessage?: boolean }) => {
    if (scenarioStep !== "awaitingTime") return;

    if (!options?.skipUserMessage) {
      setMessages((prev) => [...prev, { role: "user", content: time }]);
    }
    setSelectedTime(time);
    setScenarioStep("resultsShown");
    setSuggestions([]);
    respondWithThinking({ content: "총 10곳을 찾았어요.", variant: "totalResults" });
  };

  const handlePlaceSelect = (place: PlaceInfo) => {
    respondWithThinking({
      content: `${place.name} (${place.address}) 에서 약속을 생성할게요.`,
      variant: "bookingConfirm",
      choices: ["네", "아니오"],
      place,
    });
  };

  const handleListExpandToggle = (expanded: boolean) => {
    scrollToBottom(expanded ? "smooth" : "smooth");
  };

  const buildReservationSummary = (place: PlaceInfo): { text: string; detailUrl: string } => {
    const startTime = selectedTime ?? DEFAULT_MEETING_START;
    const endTime = addMinutesToTime(startTime, DEFAULT_MEETING_MINUTES);
    const summary = [
      "선택하신 약속에 대해서 정리해드릴게요.",
      "",
      `${place.name}에서 점심 약속이 있습니다.`,
      "",
      `- 시작: ${MEETING_DATE_LABEL} ${formatKoreanTime(startTime)}`,
      `- 종료: ${MEETING_DATE_LABEL} ${formatKoreanTime(endTime)}`,
      `- 장소: ${place.name}`,
      `- 주소: ${place.address}`,
      "",
    ].join("\n");
    return { text: summary, detailUrl: PLACE_DETAIL_URL };
  };

  const handleReservationDecision = (messageIndex: number, place: PlaceInfo | undefined, confirmed: boolean) => {
    if (!place) return;
    setMessages((prev) => {
      const next = [...prev];
      if (next[messageIndex]) {
        next[messageIndex] = { ...next[messageIndex], choices: [] };
      }
      return next;
    });

    if (confirmed) {
      const summary = buildReservationSummary(place);
      respondWithThinking({
        content: summary.text,
        variant: "bookingSummary",
        place,
        detailUrl: summary.detailUrl,
      });
    } else {
      respondWithThinking({
        content: "다른 장소도 살펴보면서 더 좋은 선택을 찾아볼까요?",
        variant: "retryPrompt",
        choices: ["네", "아니오"],
        place,
      });
    }
  };

  const handleRetryDecision = (messageIndex: number, place: PlaceInfo | undefined, restart: boolean) => {
    setMessages((prev) => {
      const next = [...prev];
      if (next[messageIndex]) {
        next[messageIndex] = { ...next[messageIndex], choices: [] };
      }
      return next;
    });
    if (!place) return;

    if (restart) {
      setScenarioStep("awaitingTime");
      setSelectedTime(null);
      setSuggestions([]);
      respondWithThinking({
        content: "처음으로 돌아갈게요. 더 정확한 정보 제공을 위해서, 몇 시쯤에 가실 예정인가요?",
        variant: "timeQuestion",
        choices: ["11:00", "12:00", "13:00"],
      });
    } else {
      handlePlaceSelect(place);
    }
  };

  const handleScenarioFlow = (query: string): boolean => {
    const normalized = query.replace(/\s/g, "");

    if ((scenarioStep === "idle" || scenarioStep === "resultsShown") && normalized.includes("피곤")) {
      setScenarioStep("awaitingFollowup");
      setSelectedTime(null);
      setSuggestions([]);
      respondWithThinking({
        content: "피곤하시겠어요. 이동 시간과 상황에 맞는 약속 장소를 바로 찾아볼게요!",
      });
      return true;
    }

    if (scenarioStep === "awaitingFollowup") {
      setScenarioStep("awaitingTime");
      setSelectedTime(null);
      setSuggestions([]);
      respondWithThinking({
        content: "더 정확한 정보 제공을 위해서, 몇 시쯤에 가실 예정인가요?",
        variant: "timeQuestion",
        choices: ["11:00", "12:00", "13:00"],
      });
      return true;
    }

    if (scenarioStep === "awaitingTime") {
      handleTimeSelection(query, { skipUserMessage: true });
      return true;
    }

    return false;
  };

  const sendMessage = async (query: string) => {
    const historyForRequest = [...messages, { role: "user" as const, content: query }].filter(
      (msg) => !msg.isLoading,
    );

    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: query }]);

    if (handleScenarioFlow(query)) return;

    setLoading(true);
    setSuggestions([]);
    setMessages((prev) => [...prev, { role: "assistant", content: "", isLoading: true }]);

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
    <div className="flex h-full flex-col bg-white text-[#1f1f1f] pb-1">
      <header className="border-b px-4 py-3 font-semibold">{label}</header>

      <div ref={scrollContainerRef} className="flex flex-1 flex-col gap-3 overflow-y-auto px-4 py-3">
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
              {msg.role === "user" ? "You" : "KANANA"}
            </div>
            {msg.isLoading ? (
              <div className="flex items-center gap-2 text-xs">
                <span className="animate-pulse rounded-full bg-[#ffeb3b] px-2 py-1 text-[11px] font-semibold text-[#1f1f1f]">
                  Thinking
                </span>
                <span className="text-gray-500">추론 중...</span>
              </div>
            ) : msg.variant === "timeQuestion" ? (
              <div className="flex flex-col gap-3">
                <p>{msg.content}</p>
                <div className="flex flex-wrap gap-2">
                  {(msg.choices ?? []).map((choice) => {
                    const isSelected = selectedTime === choice;
                    const isDisabled = scenarioStep !== "awaitingTime";
                    return (
                      <button
                        key={choice}
                        type="button"
                        onClick={() => handleTimeSelection(choice)}
                        disabled={isDisabled}
                        className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${
                          isSelected
                            ? "border-[#1f1f1f] bg-[#1f1f1f] text-white"
                            : "border-gray-300 bg-white text-gray-700 hover:bg-gray-100"
                        } ${isDisabled && !isSelected ? "opacity-50" : ""}`}
                      >
                        {choice}
                      </button>
                    );
                  })}
                </div>
                {selectedTime && scenarioStep !== "awaitingTime" && (
                  <p className="text-xs text-gray-500">선택한 시간: {selectedTime}</p>
                )}
              </div>
            ) : msg.variant === "totalResults" ? (
              <div className="flex flex-col gap-3">
                <p className="font-semibold text-gray-800">{msg.content}</p>
                <Total10 onSelect={handlePlaceSelect} onExpandToggle={handleListExpandToggle} />
              </div>
            ) : msg.variant === "bookingConfirm" && msg.place ? (
              <div className="flex flex-col gap-3">
                <p>{msg.content}</p>
                <div className="flex gap-2">
                  {(msg.choices ?? []).map((choice) => (
                    <button
                      key={choice}
                      type="button"
                      onClick={() => handleReservationDecision(idx, msg.place, choice === "네")}
                      disabled={!msg.choices?.length}
                      className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
                        choice === "네"
                          ? "bg-[#1f1f1f] text-white hover:bg-black"
                          : "border border-gray-300 bg-white text-gray-700 hover:bg-gray-100"
                      } ${!msg.choices?.length ? "cursor-not-allowed opacity-50" : ""}`}
                    >
                      {choice}
                    </button>
                  ))}
                </div>
              </div>
            ) : msg.variant === "retryPrompt" && msg.place ? (
              <div className="flex flex-col gap-3">
                <p>{msg.content}</p>
                <div className="flex gap-2">
                  {(msg.choices ?? []).map((choice) => (
                    <button
                      key={choice}
                      type="button"
                      onClick={() => handleRetryDecision(idx, msg.place, choice === "네")}
                      disabled={!msg.choices?.length}
                      className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
                        choice === "네"
                          ? "bg-[#1f1f1f] text-white hover:bg-black"
                          : "border border-gray-300 bg-white text-gray-700 hover:bg-gray-100"
                      } ${!msg.choices?.length ? "cursor-not-allowed opacity-50" : ""}`}
                    >
                      {choice}
                    </button>
                  ))}
                </div>
              </div>
            ) : msg.variant === "bookingSummary" && msg.place ? (
              <div className="flex flex-col gap-3">
                <div className="flex items-center gap-1 text-sm font-semibold text-gray-900">
                  <span>{msg.place.name}</span>
                  <a
                    href={msg.detailUrl ?? PLACE_DETAIL_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center justify-cente transition hover:border-[#fee500] hover:bg-[#fff9cc]"
                  >
                    <Image src="/assets/kakaomap_basic.png" alt="KakaoMap" width={14} height={14} />
                    <span className="sr-only">{`${msg.place.name} 카카오맵 상세로 이동`}</span>
                  </a>
                </div>
                <p className="whitespace-pre-wrap text-sm text-gray-800">{msg.content}</p>
                
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
