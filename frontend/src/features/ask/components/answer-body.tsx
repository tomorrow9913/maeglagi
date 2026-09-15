"use client";

import { Fragment } from "react";

import type { AnswerSource } from "@/lib/api";

/** 본문의 `[1]` 같은 인용 표시를 잘라내기 위한 패턴 */
const CITATION = /\[(\d+)\]/g;

/**
 * 답변 본문을 렌더링하면서 인용 번호를 누를 수 있게 만듭니다.
 *
 * 번호는 근거 카드의 순번과 1:1로 대응합니다. 근거에 없는 번호가 오면
 * 그냥 텍스트로 남겨 잘못된 이동을 만들지 않습니다.
 */
export function AnswerBody({
  text,
  sources,
  onOpenSource,
}: {
  text: string;
  sources: AnswerSource[];
  onOpenSource: (source: AnswerSource) => void;
}) {
  const byIndex = new Map(sources.map((source) => [source.index, source]));
  const parts: React.ReactNode[] = [];

  let cursor = 0;
  let match: RegExpExecArray | null;
  CITATION.lastIndex = 0;

  while ((match = CITATION.exec(text)) !== null) {
    if (match.index > cursor) parts.push(text.slice(cursor, match.index));

    const index = Number(match[1]);
    const source = byIndex.get(index);

    parts.push(
      source ? (
        <button
          key={`cite-${match.index}`}
          type="button"
          onClick={() => onOpenSource(source)}
          title={source.title}
          className="mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded bg-primary/10 px-1 align-super text-[10px] font-medium text-primary transition-colors hover:bg-primary/20"
        >
          {index}
        </button>
      ) : (
        <Fragment key={`cite-${match.index}`}>{match[0]}</Fragment>
      ),
    );

    cursor = match.index + match[0].length;
  }

  if (cursor < text.length) parts.push(text.slice(cursor));

  return <p className="text-sm leading-relaxed whitespace-pre-wrap">{parts}</p>;
}
