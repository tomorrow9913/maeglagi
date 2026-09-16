"use client";

import { AlertCircle, Loader2 } from "lucide-react";

import type { AnswerSource } from "@/lib/api";

import type { AskTurn as Turn } from "../hooks/use-ask";
import { AnswerBody } from "./answer-body";
import { MaeglagiAvatar } from "./maeglagi-avatar";
import { SourceCard } from "./source-card";

/** 질문 한 건과 그에 대한 답변·근거를 함께 보여줍니다. */
export function AskTurn({
  turn,
  onOpenSource,
}: {
  turn: Turn;
  onOpenSource: (source: AnswerSource) => void;
}) {
  const isWaiting = turn.status === "streaming" && turn.answer.length === 0;

  return (
    <li className="space-y-4">
      <div className="flex justify-end">
        <p className="max-w-[80%] rounded-2xl rounded-br-sm bg-primary px-4 py-2 text-sm text-primary-foreground">
          {turn.question}
        </p>
      </div>

      <div className="flex gap-3">
        <MaeglagiAvatar variant={isWaiting ? "resting" : "default"} />
        <div className="min-w-0 flex-1 space-y-3">
          {turn.status === "error" ? (
            <p className="flex items-start gap-2 text-sm text-destructive">
              <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
              {turn.errorMessage}
            </p>
          ) : isWaiting ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
              관련 회의와 문서를 찾아보고 있어요
            </p>
          ) : (
            <>
              <AnswerBody text={turn.answer} sources={turn.sources} onOpenSource={onOpenSource} />
              {turn.status === "aborted" ? (
                <p className="text-xs text-muted-foreground">여기서 답변을 멈췄어요.</p>
              ) : null}
            </>
          )}

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
                      onOpen={() => onOpenSource(source)}
                    />
                  </li>
                ))}
              </ul>
            </section>
          ) : turn.status === "done" ? (
            <p className="text-xs text-muted-foreground">이 답변에는 인용할 근거가 없어요.</p>
          ) : null}
        </div>
      </div>
    </li>
  );
}
