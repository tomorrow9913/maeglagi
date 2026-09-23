"use client";

import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Send, Square, Plus, FileUp, Mic, Upload } from "lucide-react";
import { toast } from "sonner";

import { DropdownMenu } from "radix-ui";
import { SourceViewer } from "@/features/source-ingestion/components/source-viewer";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { AnswerModelPicker } from "@/features/ask/components/answer-model-picker";
import { ConversationList } from "@/features/ask/components/conversation-list";
import { AskTurn } from "@/features/ask/components/ask-turn";
import { MaeglagiAvatar } from "@/features/ask/components/maeglagi-avatar";
import { QuestionInput } from "@/features/ask/components/question-input";
import {
  QUESTION_COUNTER_THRESHOLD,
  QUESTION_MAX_LENGTH,
  isNearBottom,
} from "@/features/ask/lib/ask-turns";
import { exampleQuestions } from "@/features/ask/lib/example-questions";
import { useAsk } from "@/features/ask/hooks/use-ask";
import { useAsync } from "@/hooks/use-async";
import { isMockMode } from "@/lib/api";
import { useApi, useDemoMode, useWorkspacePath } from "@/lib/api/context";
import type { AnswerSource } from "@/lib/api";
import { localDateKey } from "@/lib/format-date";
import { cn } from "@/lib/utils";

export default function AskPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const api = useApi();
  const isDemo = useDemoMode();
  const workspacePath = useWorkspacePath();
  const [sourceViewer, setSourceViewer] = useState<AnswerSource>();
  const [personalCredentialId, setPersonalCredentialId] = useState<string>();
  const { data: personalCredentials } = useAsync(
    (signal) => api.listAccountCredentials(signal),
    [],
  );

  const [draft, setDraft] = useState("");
  const [isModelSaving, setIsModelSaving] = useState(false);
  const modelSavingRef = useRef(false);
  const {
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
  } = useAsk(workspaceId, personalCredentialId);

  const onModelSavingChange = useCallback((saving: boolean) => {
    modelSavingRef.current = saving;
    setIsModelSaving(saving);
  }, []);

  /*
   * 빈 화면에는 고정 예시 대신 이 워크스페이스에 실제로 쌓인 결정을 보여줍니다.
   * "무엇을 물어볼 수 있는지"를 이 팀의 맥락으로 알려주려는 것입니다.
   */
  const { data: decisionItems, isLoading: isDecisionsLoading } = useAsync(
    (signal) => api.listContextItems(workspaceId, { kinds: ["decision"] }, signal),
    [workspaceId],
    { resetKey: workspaceId },
  );
  const recentDecisions = useMemo(
    () =>
      (decisionItems ?? [])
        .filter((item) => !item.supersededBy)
        .sort((a, b) => b.occurredAt.localeCompare(a.occurredAt))
        .slice(0, 3),
    [decisionItems],
  );

  // 소스가 하나도 없으면 무엇을 물어도 근거가 없습니다. 질문을 권하기 전에 올리기부터 안내합니다.
  const {
    data: workspace,
    isLoading: isWorkspaceLoading,
    reload: reloadWorkspace,
  } = useAsync((signal) => api.getWorkspace(workspaceId, signal), [workspaceId], {
    resetKey: workspaceId,
  });
  useEffect(() => {
    window.addEventListener("maeglagi:sources-changed", reloadWorkspace);
    return () => window.removeEventListener("maeglagi:sources-changed", reloadWorkspace);
  }, [reloadWorkspace]);

  // 예시 질문은 시드 데이터만 답할 수 있으므로 mock·데모에서만 보여줍니다.
  const showExamples = isMockMode || isDemo;
  const isIntroLoading =
    (isDecisionsLoading && !decisionItems) || (isWorkspaceLoading && !workspace);
  const hasNoSources = !showExamples && workspace?.sourceCount === 0;

  /*
   * 답변이 길어지면 마지막 줄을 따라 내려가되, 위쪽 근거를 읽으려고 올라간 사용자를
   * 끌어내리지는 않습니다. 맨 아래 근처에 있을 때만 따라갑니다.
   */
  const followRef = useRef(true);
  useEffect(() => {
    const onScroll = () => {
      followRef.current = isNearBottom({
        scrollTop: window.scrollY,
        clientHeight: window.innerHeight,
        scrollHeight: document.documentElement.scrollHeight,
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  useEffect(() => {
    if (turns.length === 0 || !followRef.current) return;
    // 부드러운 스크롤은 토큰마다 겹쳐 쌓이면서 화면을 흔들기 때문에 바로 옮깁니다.
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "auto" });
  }, [turns]);

  const submit = useCallback(
    (question: string) => {
      if (modelSavingRef.current || isStreaming || !question.trim()) return;
      setDraft("");
      followRef.current = true;
      void ask(question);
    },
    [ask, isStreaming],
  );

  const retryTurn = useCallback(
    (turnId: string) => {
      if (modelSavingRef.current || isStreaming) return;
      followRef.current = true;
      retry(turnId);
    },
    [retry, isStreaming],
  );

  const clearConversation = () => {
    const removed = clear();
    if (removed.length === 0) return;
    toast("대화를 지웠습니다.", {
      action: { label: "되돌리기", onClick: () => restore(removed) },
    });
  };

  const openSource = useCallback((source: AnswerSource) => setSourceViewer(source), []);
  const openUpload = (mode: "document" | "meeting") => {
    window.dispatchEvent(
      new CustomEvent("maeglagi:open-source-upload", { detail: { workspaceId, mode } }),
    );
  };

  const remaining = QUESTION_MAX_LENGTH - draft.length;
  const showCounter = remaining <= QUESTION_COUNTER_THRESHOLD;
  const showIntro = isRestored && turns.length === 0;

  return (
    <div className="flex min-h-[calc(100dvh-8rem)] flex-col">
      <PageHeader
        title="Ask"
        description="워크스페이스에 질문하고 근거와 함께 답을 받습니다."
        action={
          turns.length > 0 ? (
            <Button variant="ghost" size="sm" onClick={clearConversation}>
              대화 지우기
            </Button>
          ) : undefined
        }
      />
      <p className="-mt-3 mb-6 text-xs text-muted-foreground">
        이 화면의 Ask는 서비스 AI 연결을 사용합니다. 내 에이전트에서 답변을 받으려면{" "}
        <Link href="/account/mcp" className="text-primary underline-offset-2 hover:underline">
          계정 MCP 연결
        </Link>
        을 등록해 보세요.
      </p>
      {!isDemo && (personalCredentials?.length ?? 0) > 0 ? (
        <div className="-mt-3 mb-6 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <label htmlFor="ask-key-scope" className="font-medium text-foreground">
            답변 연결
          </label>
          <select
            id="ask-key-scope"
            className="h-8 rounded-md border border-input bg-background px-2 text-xs text-foreground"
            value={personalCredentialId ?? "workspace"}
            disabled={isStreaming}
            onChange={(event) =>
              setPersonalCredentialId(
                event.target.value === "workspace" ? undefined : event.target.value,
              )
            }
          >
            <option value="workspace">워크스페이스 기본 연결</option>
            {personalCredentials
              ?.filter((credential) => credential.status === "active")
              .map((credential) => (
                <option key={credential.id} value={credential.id}>
                  내 연결 · {credential.label}
                </option>
              ))}
          </select>
          <span>내 연결 선택은 이 질문의 답변에만 적용됩니다.</span>
        </div>
      ) : null}

      <details className="mb-4 rounded-xl border border-border p-3 lg:hidden">
        <summary className="cursor-pointer text-sm font-medium">최근 대화 보기</summary>
        <div className="pt-3">
          <ConversationList
            conversations={conversations}
            activeId={activeId}
            disabled={isStreaming}
            onCreate={createConversation}
            onSelect={selectConversation}
          />
        </div>
      </details>

      <div className="grid flex-1 gap-6 lg:grid-cols-[minmax(0,1fr)_15rem]">
        <div className="flex min-w-0 flex-col">
          {/* 대화가 없을 때는 안내를 입력창과 헤더 사이 가운데에 둬 빈 화면이 한쪽으로 쏠리지 않게 합니다. */}
          <div className={cn("flex-1", showIntro && "flex flex-col justify-center")}>
            {showIntro ? (
              <div className="mx-auto flex w-full max-w-xl flex-col items-center gap-4 pb-16 text-center">
                <MaeglagiAvatar variant="resting" className="size-12" />
                <div className="w-full space-y-1">
                  {isIntroLoading ? (
                    <Skeleton className="mx-auto h-6 w-56 max-w-full" />
                  ) : (
                    <p className="font-medium">
                      {hasNoSources
                        ? "아직 물어볼 소스가 없어요. 회의나 문서를 먼저 올려보세요."
                        : recentDecisions.length > 0 || showExamples
                          ? "최근 결정의 근거부터 물어보세요"
                          : "올려 둔 회의와 문서에 대해 물어보세요"}
                    </p>
                  )}
                  <p className="text-sm text-muted-foreground">
                    맥락이가 회의와 문서에서 근거를 찾아 답해요. 근거가 없으면 없다고 말해요.
                  </p>
                </div>
                {/* 불러오는 동안과 그 뒤의 높이를 같게 잡아, 목록이 들어올 때 화면이 밀리지 않게 합니다. */}
                <div className="flex min-h-[11.5rem] w-full flex-col items-center">
                  {isIntroLoading ? (
                    <div className="w-full" role="status">
                      <Skeleton className="h-[11.5rem] w-full rounded-xl" />
                      <span className="sr-only">물어볼 만한 결정을 불러오는 중</span>
                    </div>
                  ) : hasNoSources ? (
                    isDemo ? null : (
                      <Button type="button" onClick={() => openUpload("document")}>
                        <Upload aria-hidden />
                        소스 올리기
                      </Button>
                    )
                  ) : recentDecisions.length > 0 ? (
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
                              <span className="block truncate text-sm font-medium">
                                {item.title}
                              </span>
                              <span className="block text-xs text-muted-foreground tabular-nums">
                                {localDateKey(item.occurredAt)} 결정
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
                  ) : showExamples ? (
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
                  ) : null}
                </div>
              </div>
            ) : null}

            {/*
             * 새 질문과 답변 도착을 스크린리더에 알리는 영역입니다. 내용이 들어오기 전부터 있어야
             * 첫 질문도 읽히므로 비어 있어도 그려 둡니다. 쓰는 중인 본문은 AskTurn이 가려 둡니다.
             */}
            <div role="log" aria-live="polite" aria-relevant="additions" aria-label="질문과 답변">
              {turns.length > 0 ? (
                <ul className="space-y-8 pb-4">
                  {turns.map((turn) => (
                    <AskTurn
                      key={turn.id}
                      turn={turn}
                      onOpenSource={openSource}
                      onRetry={retryTurn}
                      retryDisabled={isStreaming || isModelSaving}
                      onContinueFrom={branchFrom}
                      onUpload={isDemo ? undefined : () => openUpload("document")}
                      settingsHref={workspacePath(workspaceId, "settings")}
                    />
                  ))}
                </ul>
              ) : null}
            </div>
          </div>

          <div className="sticky bottom-0 bg-background/85 pt-3 pb-2 backdrop-blur">
            <form
              className="flex items-end gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                submit(draft);
              }}
            >
              <div className="relative min-w-0 flex-1">
                <QuestionInput
                  className="pr-10"
                  value={draft}
                  placeholder="이 워크스페이스에 대해 질문해 보세요"
                  onChange={setDraft}
                  onSubmit={() => submit(draft)}
                  aria-label="질문"
                  aria-describedby="ask-input-help"
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
            <div className="mt-1 flex items-start justify-between gap-3 text-xs text-muted-foreground">
              <p id="ask-input-help">
                이 대화의 이전 문답을 참고해 답해요. 사실은 현재 근거에서 다시 확인합니다.
              </p>
              {showCounter ? (
                <p
                  className={cn("shrink-0 tabular-nums", remaining <= 0 && "text-destructive")}
                  aria-live="polite"
                >
                  <span className="sr-only">질문 글자 수 </span>
                  {draft.length.toLocaleString("ko-KR")} /{" "}
                  {QUESTION_MAX_LENGTH.toLocaleString("ko-KR")}
                </p>
              ) : null}
            </div>
            <AnswerModelPicker
              key={workspaceId}
              workspaceId={workspaceId}
              isStreaming={isStreaming}
              onSavingChange={onModelSavingChange}
            />
          </div>
        </div>
        <aside className="hidden border-l border-border pl-4 lg:block">
          <div className="sticky top-20 max-h-[calc(100dvh-7rem)] overflow-y-auto">
            <ConversationList
              conversations={conversations}
              activeId={activeId}
              disabled={isStreaming}
              onCreate={createConversation}
              onSelect={selectConversation}
            />
          </div>
        </aside>
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
