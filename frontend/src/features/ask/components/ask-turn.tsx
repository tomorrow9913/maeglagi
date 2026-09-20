"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertCircle, Check, Copy, GitBranch, RotateCcw, Upload } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type { AnswerSource } from "@/lib/api";

import { NO_EVIDENCE_MESSAGE, waitingLabel, type AskTurn as Turn } from "../lib/ask-turns";
import { AnswerBody } from "./answer-body";
import { MaeglagiAvatar } from "./maeglagi-avatar";
import { SourceCard } from "./source-card";

/** 질문 한 건과 그에 대한 답변·근거를 함께 보여줍니다. */
export function AskTurn({
  turn,
  onOpenSource,
  onRetry,
  onUpload,
  settingsHref,
  retryDisabled = false,
  onContinueFrom,
}: {
  turn: Turn;
  onOpenSource: (source: AnswerSource) => void;
  /** 실패한 질문을 같은 문장으로 다시 묻습니다. */
  onRetry?: (turnId: string) => void;
  /** 소스 업로드를 엽니다. 읽기 전용 데모에서는 넘기지 않습니다. */
  onUpload?: () => void;
  /** AI 연결을 등록하는 설정 화면. 모델이 없어 실패한 질문에 붙입니다. */
  settingsHref?: string;
  /** 다른 질문이 진행 중이면 다시 시도를 잠급니다. */
  retryDisabled?: boolean;
  onContinueFrom?: (turnId: string) => void;
}) {
  const isStreaming = turn.status === "streaming";
  const isWaiting = isStreaming && turn.answer.length === 0;
  // 이 화면에서 답변이 끝나는 것을 본 질문만 도착을 알립니다. 복원된 질문은 알리지 않습니다.
  const [startedLive] = useState(isStreaming);
  const [copied, setCopied] = useState(false);

  const copyAnswer = async () => {
    try {
      await navigator.clipboard.writeText(turn.answer);
      setCopied(true);
      toast.success("답변을 복사했습니다.");
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("답변을 복사하지 못했습니다.");
    }
  };

  return (
    <li className="space-y-4">
      <div className="flex justify-end">
        <p className="max-w-[80%] rounded-2xl rounded-br-sm bg-primary px-4 py-2 text-sm [overflow-wrap:anywhere] break-words whitespace-pre-wrap text-primary-foreground">
          <span className="sr-only">질문: </span>
          {turn.question}
        </p>
      </div>

      <div className="flex gap-3">
        <MaeglagiAvatar variant={isWaiting ? "resting" : "default"} />
        <div className="min-w-0 flex-1 space-y-3">
          {turn.status === "no_evidence" ? (
            // 근거 없음은 실패가 아니라 맥락이의 정상 답변입니다.
            <div className="space-y-3">
              <p className="text-sm leading-relaxed [overflow-wrap:anywhere] break-words">
                {NO_EVIDENCE_MESSAGE}
              </p>
              {onUpload ? (
                <Button type="button" variant="outline" size="sm" onClick={onUpload}>
                  <Upload aria-hidden />
                  소스 올리기
                </Button>
              ) : null}
            </div>
          ) : null}

          {turn.answer.length > 0 && turn.status !== "no_evidence" ? (
            // 토큰마다 읽히지 않도록 쓰는 동안에는 스크린리더에서 가리고, 끝나면 한 번만 알립니다.
            <div aria-hidden={isStreaming || undefined}>
              <AnswerBody
                text={turn.answer}
                sources={turn.sources}
                onOpenSource={onOpenSource}
                streaming={isStreaming}
              />
            </div>
          ) : null}

          {isWaiting ? (
            <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
              <Spinner className="size-3.5" />
              {waitingLabel(turn)}
            </p>
          ) : null}

          {turn.status === "done" && startedLive ? (
            <p className="sr-only">답변이 도착했습니다.</p>
          ) : null}

          {turn.status === "aborted" ? (
            <p className="text-xs text-muted-foreground">여기서 답변을 멈췄어요.</p>
          ) : null}

          {turn.status === "error" ? (
            // 받은 본문은 위에 그대로 두고, 그 아래에 무엇이 실패했는지와 다음 행동을 붙입니다.
            <div className="space-y-2">
              <p role="alert" className="flex items-start gap-2 text-sm text-destructive">
                <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
                <span className="min-w-0 break-words">{turn.errorMessage}</span>
              </p>
              <div className="flex flex-wrap items-center gap-2">
                {onRetry ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={retryDisabled}
                    onClick={() => onRetry(turn.id)}
                  >
                    <RotateCcw aria-hidden />
                    다시 시도
                  </Button>
                ) : null}
                {turn.errorAction === "settings" && settingsHref ? (
                  <Button asChild variant="ghost" size="sm">
                    <Link href={settingsHref}>설정에서 AI 연결 등록</Link>
                  </Button>
                ) : null}
              </div>
            </div>
          ) : null}

          {turn.sources.length > 0 ? (
            <section>
              <h3 className="mb-2 text-xs font-medium text-muted-foreground">
                근거 {turn.sources.length}건
              </h3>
              <ul className="space-y-2">
                {turn.sources.map((source) => (
                  <li key={`${source.sourceId}-${source.index}`}>
                    <SourceCard
                      index={source.index}
                      kind={source.kind}
                      title={source.title}
                      excerpt={source.excerpt}
                      timestamp={source.timestamp}
                      onOpen={() => onOpenSource(source)}
                    />
                  </li>
                ))}
              </ul>
            </section>
          ) : turn.status === "done" ? (
            <p className="text-xs text-muted-foreground">이 답변에는 인용할 근거가 없어요.</p>
          ) : null}

          {(turn.status === "done" || turn.status === "aborted") && turn.answer.length > 0 ? (
            <Button
              type="button"
              variant="ghost"
              size="xs"
              className="-ml-2 text-muted-foreground"
              onClick={() => void copyAnswer()}
            >
              {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
              답변 복사
            </Button>
          ) : null}
          {turn.status === "done" && onContinueFrom ? (
            <Button
              type="button"
              variant="ghost"
              size="xs"
              disabled={retryDisabled}
              className="text-muted-foreground"
              onClick={() => onContinueFrom(turn.id)}
            >
              <GitBranch aria-hidden /> 이 시점부터 이어가기
            </Button>
          ) : null}
        </div>
      </div>
    </li>
  );
}
