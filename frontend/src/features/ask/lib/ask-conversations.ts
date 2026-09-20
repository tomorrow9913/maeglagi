import { parseTurns, serializeTurns, type AskTurn } from "./ask-turns";

export type AskConversation = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  turns: AskTurn[];
};

const VERSION = 1;
const MAX_CONVERSATIONS = 10;

export function recentConversations(conversations: AskConversation[]): AskConversation[] {
  return [...conversations]
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
    .slice(0, MAX_CONVERSATIONS);
}

export function conversationsStorageKey(workspaceId: string): string {
  return `maeglagi:ask:conversations:${workspaceId}`;
}

export function newConversation(id: string, now = new Date().toISOString()): AskConversation {
  return { id, title: "새 대화", createdAt: now, updatedAt: now, turns: [] };
}

export function withTurns(conversation: AskConversation, turns: AskTurn[]): AskConversation {
  return {
    ...conversation,
    title: turns[0]?.question.slice(0, 60) || "새 대화",
    updatedAt: new Date().toISOString(),
    turns,
  };
}

export function historyBefore(turns: AskTurn[]): { question: string; answer: string }[] {
  return turns
    .filter((turn) => turn.status === "done" && turn.answer.trim())
    .slice(-6)
    .map((turn) => ({ question: turn.question, answer: turn.answer.slice(0, 4000) }));
}

export function serializeConversations(conversations: AskConversation[], activeId: string): string {
  const stored = recentConversations(conversations)
    .map((conversation) => ({
      ...conversation,
      turns: JSON.parse(serializeTurns(conversation.turns)).turns as AskTurn[],
    }));
  return JSON.stringify({ version: VERSION, activeId, conversations: stored });
}

export function parseConversations(raw: string | null): {
  activeId: string;
  conversations: AskConversation[];
} | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (parsed.version !== VERSION || !Array.isArray(parsed.conversations)) return null;
    const conversations = parsed.conversations
      .filter((item): item is AskConversation =>
        Boolean(
          item &&
          typeof item === "object" &&
          typeof item.id === "string" &&
          typeof item.title === "string" &&
          typeof item.createdAt === "string" &&
          typeof item.updatedAt === "string",
        ),
      )
      .slice(0, MAX_CONVERSATIONS)
      .map((item) => ({
        ...item,
        turns: parseTurns(JSON.stringify({ version: 1, turns: item.turns })),
      }));
    if (conversations.length === 0) return null;
    return {
      conversations,
      activeId: conversations.some((item) => item.id === parsed.activeId)
        ? String(parsed.activeId)
        : conversations[0].id,
    };
  } catch {
    return null;
  }
}
