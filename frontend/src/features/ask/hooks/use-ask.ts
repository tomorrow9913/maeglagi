"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import { useApi } from "@/lib/api/context";
import { toUserMessage } from "@/lib/api/error-message";

import {
  ASK_FAILED_MESSAGE,
  failTurn,
  newTurn,
  parseTurns,
  reduceTurn,
  serializeTurns,
  settleTurn,
  turnsStorageKey,
  type AskTurn,
} from "../lib/ask-turns";

export type { AskTurn };

/** 저장소를 못 쓰는 환경(사파리 개인정보 보호 모드 등)에서도 화면은 그대로 동작해야 합니다. */
function readStoredTurns(workspaceId: string): AskTurn[] {
  try {
    return parseTurns(window.sessionStorage.getItem(turnsStorageKey(workspaceId)));
  } catch {
    return [];
  }
}

function writeStoredTurns(workspaceId: string, turns: AskTurn[]) {
  try {
    const key = turnsStorageKey(workspaceId);
    if (turns.some((turn) => turn.status !== "streaming")) {
      window.sessionStorage.setItem(key, serializeTurns(turns));
    } else {
      window.sessionStorage.removeItem(key);
    }
  } catch {
    // 저장에 실패해도 대화 자체에는 영향이 없습니다.
  }
}

/**
 * Ask 대화를 관리합니다.
 *
 * 한 번에 한 질문만 처리합니다. 끝난 질문은 워크스페이스별로 sessionStorage에 남겨
 * 다른 화면에 다녀와도 이어서 볼 수 있게 합니다. 진행 중이던 질문은 되살리지 않습니다.
 */
export function useAsk(workspaceId: string) {
  const api = useApi();
  // 어느 워크스페이스의 대화인지 함께 기억해, 복원 전이나 전환 직후에 엉뚱한 내용을 저장하지 않습니다.
  const [state, setState] = useState<{ workspaceId?: string; turns: AskTurn[] }>({ turns: [] });
  const [isStreaming, setIsStreaming] = useState(false);

  const controllerRef = useRef<AbortController>(null);
  const inFlightRef = useRef(false);
  const sequence = useRef(0);

  const isRestored = state.workspaceId === workspaceId;
  const turns = isRestored ? state.turns : EMPTY;

  useEffect(() => {
    setState({ workspaceId, turns: readStoredTurns(workspaceId) });
    setIsStreaming(false);
    inFlightRef.current = false;
    return () => controllerRef.current?.abort();
  }, [workspaceId]);

  useEffect(() => {
    if (state.workspaceId === workspaceId) writeStoredTurns(workspaceId, state.turns);
  }, [state, workspaceId]);

  const setTurns = useCallback((update: (current: AskTurn[]) => AskTurn[]) => {
    setState((current) => ({ ...current, turns: update(current.turns) }));
  }, []);

  const run = useCallback(
    async (question: string, replaceId?: string) => {
      const trimmed = question.trim();
      if (!trimmed || inFlightRef.current) return;
      inFlightRef.current = true;

      // 복원된 질문과 겹치지 않도록 시각을 섞어 id를 만듭니다.
      const id = `turn-${Date.now().toString(36)}-${++sequence.current}`;
      let turn = newTurn(id, trimmed);
      const commit = (next: AskTurn) => {
        turn = next;
        setTurns((current) => current.map((item) => (item.id === id ? next : item)));
      };

      // 다시 시도는 실패한 질문을 지우고 같은 질문을 맨 아래에서 새로 시작합니다.
      setTurns((current) => [...current.filter((item) => item.id !== replaceId), turn]);
      setIsStreaming(true);

      const controller = new AbortController();
      controllerRef.current = controller;

      try {
        for await (const event of api.ask(workspaceId, trimmed, controller.signal)) {
          commit(reduceTurn(turn, event));
          if (turn.status !== "streaming") break;
        }
        /*
         * 스트림이 `done`/`error` 없이 끝나는 경우가 둘 있습니다. 중단을 누르면 reader가
         * 취소되면서 예외 없이 끝나고, 프록시 타임아웃처럼 연결이 끊겨도 그냥 끝납니다.
         * 어느 쪽이든 "streaming"으로 남겨 두면 대기 표시가 영원히 돕니다.
         */
        commit(settleTurn(turn, controller.signal.aborted ? "aborted" : "disconnected"));
      } catch (error) {
        const aborted =
          controller.signal.aborted ||
          (error instanceof DOMException && error.name === "AbortError");
        if (aborted) {
          commit(settleTurn(turn, "aborted"));
        } else {
          // 422는 답변 모델이나 AI 연결이 없을 때 옵니다. 설정으로 가는 길을 함께 보여줍니다.
          const needsModel =
            error instanceof ApiError && error.kind === "invalid" && error.status === 422;
          commit(
            failTurn(
              turn,
              toUserMessage(error, ASK_FAILED_MESSAGE),
              needsModel ? "settings" : undefined,
            ),
          );
        }
      } finally {
        inFlightRef.current = false;
        setIsStreaming(false);
        if (controllerRef.current === controller) controllerRef.current = null;
      }
    },
    [workspaceId, setTurns, api],
  );

  const ask = useCallback((question: string) => run(question), [run]);

  /** 실패한 질문을 같은 문장으로 다시 묻습니다. 질문이 두 번 쌓이지 않게 실패한 쪽은 지웁니다. */
  const retry = useCallback(
    (turnId: string) => {
      const target = state.turns.find((turn) => turn.id === turnId);
      if (target) void run(target.question, turnId);
    },
    [run, state.turns],
  );

  const stop = useCallback(() => controllerRef.current?.abort(), []);

  /** 대화를 비우고, 되돌릴 수 있게 지운 내용을 돌려줍니다. 진행 중이던 질문은 멈춘 상태로 담깁니다. */
  const clear = useCallback((): AskTurn[] => {
    controllerRef.current?.abort();
    const removed = state.turns.map((turn) => settleTurn(turn, "aborted"));
    setTurns(() => []);
    return removed;
  }, [setTurns, state.turns]);

  /** `clear`가 돌려준 내용을 되살립니다. 그 사이 새로 물은 질문은 뒤에 그대로 둡니다. */
  const restore = useCallback(
    (removed: AskTurn[]) => {
      setTurns((current) => {
        const existing = new Set(current.map((turn) => turn.id));
        return [...removed.filter((turn) => !existing.has(turn.id)), ...current];
      });
    },
    [setTurns],
  );

  return { turns, isStreaming, isRestored, ask, retry, stop, clear, restore };
}

const EMPTY: AskTurn[] = [];
