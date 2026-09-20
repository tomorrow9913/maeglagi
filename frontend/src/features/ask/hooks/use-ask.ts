"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import { useApi } from "@/lib/api/context";
import { toUserMessage } from "@/lib/api/error-message";
import {
  conversationsStorageKey,
  historyBefore,
  newConversation,
  parseConversations,
  recentConversations,
  serializeConversations,
  withTurns,
  type AskConversation,
} from "../lib/ask-conversations";
import {
  ASK_FAILED_MESSAGE,
  failTurn,
  newTurn,
  parseTurns,
  reduceTurn,
  settleTurn,
  turnsStorageKey,
  type AskTurn,
} from "../lib/ask-turns";

export type { AskTurn };
type State = { workspaceId?: string; activeId: string; conversations: AskConversation[] };
const EMPTY: AskTurn[] = [];

function identifier(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

function readStored(workspaceId: string): State {
  try {
    const stored = parseConversations(localStorage.getItem(conversationsStorageKey(workspaceId)));
    if (stored) return { workspaceId, ...stored };
    const legacy = parseTurns(sessionStorage.getItem(turnsStorageKey(workspaceId)));
    const first = withTurns(newConversation(identifier("conversation")), legacy);
    sessionStorage.removeItem(turnsStorageKey(workspaceId));
    return { workspaceId, activeId: first.id, conversations: [first] };
  } catch {
    const first = newConversation(identifier("conversation"));
    return { workspaceId, activeId: first.id, conversations: [first] };
  }
}

export function useAsk(workspaceId: string) {
  const api = useApi();
  const [state, setState] = useState<State>({ activeId: "", conversations: [] });
  const [isStreaming, setIsStreaming] = useState(false);
  const controllerRef = useRef<AbortController>(null);
  const inFlightRef = useRef(false);

  const isRestored = state.workspaceId === workspaceId;
  const conversations = isRestored ? state.conversations : [];
  const activeId = isRestored ? state.activeId : "";
  const turns = conversations.find((item) => item.id === activeId)?.turns ?? EMPTY;

  useEffect(() => {
    setState(readStored(workspaceId));
    setIsStreaming(false);
    inFlightRef.current = false;
    return () => controllerRef.current?.abort();
  }, [workspaceId]);

  useEffect(() => {
    if (!isRestored || isStreaming) return;
    try {
      localStorage.setItem(
        conversationsStorageKey(workspaceId),
        serializeConversations(state.conversations, state.activeId),
      );
    } catch {
      // Storage may be unavailable; the current conversation still works.
    }
  }, [state, workspaceId, isRestored, isStreaming]);

  const setTurns = useCallback(
    (update: (current: AskTurn[]) => AskTurn[]) => {
      setState((current) => {
        if (current.workspaceId !== workspaceId) return current;
        return {
          ...current,
          conversations: current.conversations.map((conversation) =>
            conversation.id === current.activeId
              ? withTurns(conversation, update(conversation.turns))
              : conversation,
          ),
        };
      });
    },
    [workspaceId],
  );

  const run = useCallback(
    async (question: string, replaceId?: string) => {
      const trimmed = question.trim();
      if (!trimmed || inFlightRef.current || !isRestored) return;
      inFlightRef.current = true;
      const history = historyBefore(turns.filter((item) => item.id !== replaceId));
      const id = identifier("turn");
      let turn = newTurn(id, trimmed);
      const commit = (next: AskTurn) => {
        turn = next;
        setTurns((current) => current.map((item) => (item.id === id ? next : item)));
      };

      setTurns((current) => [...current.filter((item) => item.id !== replaceId), turn]);
      setIsStreaming(true);
      const controller = new AbortController();
      controllerRef.current = controller;

      try {
        for await (const event of api.ask(workspaceId, trimmed, controller.signal, history)) {
          commit(reduceTurn(turn, event));
          if (turn.status !== "streaming") break;
        }
        commit(settleTurn(turn, controller.signal.aborted ? "aborted" : "disconnected"));
      } catch (error) {
        const aborted =
          controller.signal.aborted ||
          (error instanceof DOMException && error.name === "AbortError");
        if (aborted) {
          commit(settleTurn(turn, "aborted"));
        } else {
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
    [workspaceId, setTurns, api, turns, isRestored],
  );

  const ask = useCallback((question: string) => run(question), [run]);
  const retry = useCallback(
    (turnId: string) => {
      const target = turns.find((turn) => turn.id === turnId);
      if (target) void run(target.question, turnId);
    },
    [run, turns],
  );
  const stop = useCallback(() => controllerRef.current?.abort(), []);

  const createConversation = useCallback(() => {
    if (inFlightRef.current) return;
    const conversation = newConversation(identifier("conversation"));
    setState((current) => ({
      ...current,
      activeId: conversation.id,
      conversations: recentConversations([conversation, ...current.conversations]),
    }));
  }, []);

  const selectConversation = useCallback((id: string) => {
    if (inFlightRef.current) return;
    setState((current) =>
      current.conversations.some((item) => item.id === id) ? { ...current, activeId: id } : current,
    );
  }, []);

  const branchFrom = useCallback(
    (turnId: string) => {
      if (inFlightRef.current) return;
      const index = turns.findIndex((turn) => turn.id === turnId);
      if (index < 0) return;
      const conversation = withTurns(
        newConversation(identifier("conversation")),
        turns.slice(0, index + 1).filter((turn) => turn.status !== "streaming"),
      );
      setState((current) => ({
        ...current,
        activeId: conversation.id,
        conversations: recentConversations([conversation, ...current.conversations]),
      }));
    },
    [turns],
  );

  const clear = useCallback((): AskTurn[] => {
    controllerRef.current?.abort();
    const removed = turns.map((turn) => settleTurn(turn, "aborted"));
    setTurns(() => []);
    return removed;
  }, [setTurns, turns]);

  const restore = useCallback(
    (removed: AskTurn[]) => {
      setTurns((current) => {
        const existing = new Set(current.map((turn) => turn.id));
        return [...removed.filter((turn) => !existing.has(turn.id)), ...current];
      });
    },
    [setTurns],
  );

  return {
    turns,
    conversations,
    activeId,
    isStreaming,
    isRestored,
    ask,
    retry,
    stop,
    clear,
    restore,
    createConversation,
    selectConversation,
    branchFrom,
  };
}
