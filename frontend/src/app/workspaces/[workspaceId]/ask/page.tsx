"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Send, Square } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AskTurn } from "@/features/ask/components/ask-turn";
import { MaeglagiAvatar } from "@/features/ask/components/maeglagi-avatar";
import { exampleQuestions } from "@/features/ask/lib/example-questions";
import { useAsk } from "@/features/ask/hooks/use-ask";
import type { AnswerSource } from "@/lib/api";
import { workspacePath } from "@/lib/navigation";

export default function AskPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const router = useRouter();

  const [draft, setDraft] = useState("");
  const { turns, isStreaming, ask, stop, clear } = useAsk(workspaceId);

  // 답변이 길어져도 마지막 줄이 보이도록 따라 내려갑니다.
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  const submit = useCallback(
    (question: string) => {
      setDraft("");
      void ask(question);
    },
    [ask],
  );

  const openSource = useCallback(
    (source: AnswerSource) => {
      const query = new URLSearchParams({ source: source.sourceId, chunk: source.chunkId });
      router.push(`${workspacePath(workspaceId, "sources")}?${query.toString()}`);
    },
    [router, workspaceId],
  );

  return (
    <div className="flex min-h-[calc(100dvh-8rem)] flex-col">
      <PageHeader
        title="Ask Workspace"
        description="워크스페이스에 질문하고 근거와 함께 답을 받습니다."
        action={
          turns.length > 0 ? (
            <Button variant="ghost" size="sm" onClick={clear}>
              대화 지우기
            </Button>
          ) : undefined
        }
      />

      <div className="flex-1">
        {turns.length === 0 ? (
          <div className="flex flex-col items-center gap-4 py-16 text-center">
            <MaeglagiAvatar variant="resting" className="size-12" />
            <div className="space-y-1">
              <p className="font-medium">무엇이든 물어보세요</p>
              <p className="text-sm text-muted-foreground">
                회의와 문서에서 근거를 찾아 답합니다. 근거가 없으면 없다고 답합니다.
              </p>
            </div>
            <ul className="flex flex-wrap justify-center gap-2">
              {exampleQuestions.map((question) => (
                <li key={question}>
                  <button
                    type="button"
                    onClick={() => submit(question)}
                    className="rounded-full border border-border px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
                  >
                    {question}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <ul className="space-y-8 pb-4">
            {turns.map((turn) => (
              <AskTurn key={turn.id} turn={turn} onOpenSource={openSource} />
            ))}
          </ul>
        )}
        <div ref={bottomRef} />
      </div>

      <form
        className="sticky bottom-0 flex gap-2 bg-background/85 py-4 backdrop-blur"
        onSubmit={(event) => {
          event.preventDefault();
          submit(draft);
        }}
      >
        <Input
          value={draft}
          placeholder="이 워크스페이스에 대해 질문하세요"
          disabled={isStreaming}
          onChange={(event) => setDraft(event.target.value)}
          aria-label="질문"
        />
        {isStreaming ? (
          <Button type="button" variant="outline" onClick={stop}>
            <Square className="size-4" aria-hidden />
            중단
          </Button>
        ) : (
          <Button type="submit" disabled={!draft.trim()}>
            <Send className="size-4" aria-hidden />
            보내기
          </Button>
        )}
      </form>
    </div>
  );
}
