"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { AnswerSource } from "@/lib/api";

export type AskTurn = {
  id: string;
  question: string;
  /** 스트리밍으로 채워지는 답변 본문 */
  answer: string;
  sources: AnswerSource[];
  status: "streaming" | "done" | "error" | "aborted";
  errorMessage?: string;
};

/**
 * Ask 대화를 관리합니다.
 *
 * 한 번에 한 질문만 처리하고, 이력은 화면이 살아 있는 동안 유지합니다.
 * 워크스페이스가 바뀌면 이력을 비웁니다.
 */
export function useAsk(workspaceId: string) {
  const [turns, setTurns] = useState<AskTurn[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);

  const controllerRef = useRef<AbortController>(null);
  const sequence = useRef(0);

  useEffect(() => {
    setTurns([]);
    setIsStreaming(false);
    return () => controllerRef.current?.abort();
  }, [workspaceId]);

  const patch = useCallback((id: string, changes: Partial<AskTurn>) => {
    setTurns((current) => current.map((turn) => (turn.id === id ? { ...turn, ...changes } : turn)));
  }, []);

  const ask = useCallback(
    async (question: string) => {
      const trimmed = question.trim();
      if (!trimmed || isStreaming) return;

      const id = `turn-${++sequence.current}`;
      setTurns((current) => [
        ...current,
        { id, question: trimmed, answer: "", sources: [], status: "streaming" },
      ]);
      setIsStreaming(true);

      const controller = new AbortController();
      controllerRef.current = controller;

      try {
        // 토큰마다 setState를 부르면 렌더가 과해져, 본문은 지역 변수에 모읍니다.
        let answer = "";

        for await (const event of api.ask(workspaceId, trimmed, controller.signal)) {
          if (event.type === "sources") {
            patch(id, { sources: event.sources });
          } else if (event.type === "token") {
            answer += event.text;
            patch(id, { answer });
          } else if (event.type === "error") {
            patch(id, { status: "error", errorMessage: event.message });
            return;
          } else if (event.type === "done") {
            patch(id, { status: "done", answer });
          }
        }
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          patch(id, { status: "aborted" });
          return;
        }
        patch(id, {
          status: "error",
          errorMessage: error instanceof Error ? error.message : "답변을 받지 못했습니다.",
        });
      } finally {
        setIsStreaming(false);
        controllerRef.current = null;
      }
    },
    [workspaceId, isStreaming, patch],
  );

  const stop = useCallback(() => controllerRef.current?.abort(), []);
  const clear = useCallback(() => {
    controllerRef.current?.abort();
    setTurns([]);
  }, []);

  return { turns, isStreaming, ask, stop, clear };
}
