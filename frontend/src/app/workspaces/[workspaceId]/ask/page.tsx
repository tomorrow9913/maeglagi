"use client";

import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, Send, Square, Plus, FileUp, Mic } from "lucide-react";

import { DropdownMenu } from "radix-ui";
import { SourceViewer } from "@/features/source-ingestion/components/source-viewer";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AnswerModelPicker } from "@/features/ask/components/answer-model-picker";
import { AskTurn } from "@/features/ask/components/ask-turn";
import { MaeglagiAvatar } from "@/features/ask/components/maeglagi-avatar";
import { exampleQuestions } from "@/features/ask/lib/example-questions";
import { useAsk } from "@/features/ask/hooks/use-ask";
import { useAsync } from "@/hooks/use-async";
import { useApi } from "@/lib/api/context";
import type { AnswerSource } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function AskPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const api = useApi();
  const [sourceViewer, setSourceViewer] = useState<AnswerSource>();

  const [draft, setDraft] = useState("");
  const [isModelSaving, setIsModelSaving] = useState(false);
  const modelSavingRef = useRef(false);
  const { turns, isStreaming, ask, stop, clear } = useAsk(workspaceId);

  const onModelSavingChange = useCallback((saving: boolean) => {
    modelSavingRef.current = saving;
    setIsModelSaving(saving);
  }, []);

  /*
   * 빈 화면에는 고정 예시 대신 이 워크스페이스에 실제로 쌓인 결정을 보여줍니다.
   * "무엇을 물어볼 수 있는지"를 이 팀의 맥락으로 알려주려는 것입니다.
   * 불러오지 못하거나 결정이 없으면 예시 질문으로 돌아갑니다.
   */
  const { data: decisionItems } = useAsync(
    (signal) => api.listContextItems(workspaceId, { kinds: ["decision"] }, signal),
    [workspaceId],
  );
  const recentDecisions = useMemo(
    () =>
      (decisionItems ?? [])
        .filter((item) => !item.supersededBy)
        .sort((a, b) => b.occurredAt.localeCompare(a.occurredAt))
        .slice(0, 3),
    [decisionItems],
  );

  // 답변이 길어져도 마지막 줄이 보이도록 따라 내려갑니다.
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  const submit = useCallback(
    (question: string) => {
      if (modelSavingRef.current || isStreaming || !question.trim()) return;
      setDraft("");
      void ask(question);
    },
    [ask, isStreaming],
  );

  const openSource = useCallback((source: AnswerSource) => setSourceViewer(source), []);
  const openUpload = (mode: "document" | "meeting") => {
    window.dispatchEvent(
      new CustomEvent("maeglagi:open-source-upload", { detail: { workspaceId, mode } }),
    );
  };

  return (
    <div className="flex min-h-[calc(100dvh-8rem)] flex-col">
      <PageHeader
        title="Ask"
        description="워크스페이스에 질문하고 근거와 함께 답을 받습니다."
        action={
          turns.length > 0 ? (
            <Button variant="ghost" size="sm" onClick={clear}>
              대화 지우기
            </Button>
          ) : undefined
        }
      />

      {/* 대화가 없을 때는 안내를 입력창과 헤더 사이 가운데에 둬 빈 화면이 한쪽으로 쏠리지 않게 합니다. */}
      <div className={cn("flex-1", turns.length === 0 && "flex flex-col justify-center")}>
        {turns.length === 0 ? (
          <div className="mx-auto flex w-full max-w-xl flex-col items-center gap-4 pb-16 text-center">
            <MaeglagiAvatar variant="resting" className="size-12" />
            <div className="space-y-1">
              <p className="font-medium">최근 결정의 근거부터 물어보세요</p>
              <p className="text-sm text-muted-foreground">
                맥락이가 회의와 문서에서 근거를 찾아 답해요. 근거가 없으면 없다고 말해요.
              </p>
            </div>
            {recentDecisions.length > 0 ? (
              <ul className="w-full divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
                {recentDecisions.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      disabled={isStreaming || isModelSaving}
                      onClick={() => submit(`'${item.title}' 결정의 근거는 무엇인가요?`)}
                      className="group flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-accent/50"
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{item.title}</span>
                        <span className="block text-xs text-muted-foreground tabular-nums">
                          {item.occurredAt.slice(0, 10)} 결정
                        </span>
                      </span>
                      <ArrowUpRight
                        className="size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-foreground"
                        aria-hidden
                      />
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <ul className="flex flex-wrap justify-center gap-2">
                {exampleQuestions.map((question) => (
                  <li key={question}>
                    <button
                      type="button"
                      disabled={isStreaming || isModelSaving}
                      onClick={() => submit(question)}
                      className="rounded-full border border-border px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
                    >
                      {question}
                    </button>
                  </li>
                ))}
              </ul>
            )}
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

      <div className="sticky bottom-0 bg-background/85 pt-3 pb-2 backdrop-blur">
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            submit(draft);
          }}
        >
          <div className="relative min-w-0 flex-1">
            <Input
              className="pr-10"
              value={draft}
              placeholder="이 워크스페이스에 대해 질문해 보세요"
              disabled={isStreaming || isModelSaving}
              onChange={(event) => setDraft(event.target.value)}
              aria-label="질문"
            />
            <DropdownMenu.Root>
              <DropdownMenu.Trigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  className="absolute top-1 right-1"
                  aria-label="소스 추가"
                  title="파일 업로드 또는 회의 녹음"
                >
                  <Plus aria-hidden />
                </Button>
              </DropdownMenu.Trigger>
              <DropdownMenu.Portal>
                <DropdownMenu.Content
                  align="end"
                  side="top"
                  sideOffset={8}
                  className="z-50 min-w-44 rounded-lg border bg-popover p-1 text-sm shadow-md"
                >
                  <DropdownMenu.Item
                    className="flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 outline-none focus:bg-accent"
                    onSelect={() => openUpload("document")}
                  >
                    <FileUp className="size-4" />
                    파일 업로드
                  </DropdownMenu.Item>
                  <DropdownMenu.Item
                    className="flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 outline-none focus:bg-accent"
                    onSelect={() => openUpload("meeting")}
                  >
                    <Mic className="size-4" />
                    회의 녹음 · 받아쓰기
                  </DropdownMenu.Item>
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu.Root>
          </div>
          {isStreaming ? (
            <Button type="button" variant="outline" onClick={stop}>
              <Square className="size-4" aria-hidden />
              중단
            </Button>
          ) : (
            <Button type="submit" disabled={!draft.trim() || isModelSaving}>
              <Send className="size-4" aria-hidden />
              보내기
            </Button>
          )}
        </form>
        <AnswerModelPicker
          key={workspaceId}
          workspaceId={workspaceId}
          isStreaming={isStreaming}
          onSavingChange={onModelSavingChange}
        />
      </div>
      <SourceViewer
        workspaceId={workspaceId}
        sourceId={sourceViewer?.sourceId}
        highlightChunkId={sourceViewer?.chunkId}
        onClose={() => setSourceViewer(undefined)}
      />
    </div>
  );
}
