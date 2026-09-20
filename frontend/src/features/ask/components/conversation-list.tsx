"use client";

import { MessageSquarePlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { AskConversation } from "../lib/ask-conversations";

export function ConversationList({
  conversations,
  activeId,
  disabled,
  onCreate,
  onSelect,
}: {
  conversations: AskConversation[];
  activeId: string;
  disabled: boolean;
  onCreate: () => void;
  onSelect: (id: string) => void;
}) {
  return (
    <nav aria-label="최근 대화" className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">최근 대화</h2>
        <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={onCreate}>
          <MessageSquarePlus aria-hidden /> 새 대화
        </Button>
      </div>
      <ul className="space-y-1">
        {[...conversations]
          .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
          .map((conversation) => (
            <li key={conversation.id}>
              <button
                type="button"
                disabled={disabled}
                aria-current={conversation.id === activeId ? "page" : undefined}
                onClick={() => onSelect(conversation.id)}
                className={cn(
                  "w-full rounded-lg px-3 py-2 text-left transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50",
                  conversation.id === activeId && "bg-accent",
                )}
              >
                <span className="block truncate text-sm font-medium">{conversation.title}</span>
                <span className="block text-xs text-muted-foreground">
                  {new Date(conversation.updatedAt).toLocaleDateString("ko-KR")} ·{" "}
                  {conversation.turns.length}개 문답
                </span>
              </button>
            </li>
          ))}
      </ul>
      <p className="px-3 text-xs text-muted-foreground">대화 기록은 이 브라우저에 저장됩니다.</p>
    </nav>
  );
}
