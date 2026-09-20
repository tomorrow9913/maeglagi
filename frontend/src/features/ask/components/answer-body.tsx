"use client";

import { Fragment, useMemo } from "react";

import type { AnswerSource } from "@/lib/api";
import { cn } from "@/lib/utils";

import { parseAnswer, type InlineNode } from "../lib/answer-markup";

/**
 * 답변 본문을 렌더링하면서 인용 번호를 누를 수 있게 만듭니다.
 *
 * 번호는 근거 카드의 순번과 1:1로 대응합니다. 근거에 없는 번호가 오면
 * 그냥 텍스트로 남겨 잘못된 이동을 만들지 않습니다. 굵게·코드·목록 표기는
 * `answer-markup`이 구조로 나눠 주고, 여기서는 그 구조만 그립니다.
 */
export function AnswerBody({
  text,
  sources,
  onOpenSource,
  streaming = false,
  className,
}: {
  text: string;
  sources: AnswerSource[];
  onOpenSource: (source: AnswerSource) => void;
  /** 토큰이 아직 들어오는 중이면 본문 끝에 진행 표시를 붙입니다. */
  streaming?: boolean;
  className?: string;
}) {
  const blocks = useMemo(() => parseAnswer(text), [text]);
  const byIndex = new Map(sources.map((source) => [source.index, source]));

  const renderInline = (nodes: InlineNode[], keyPrefix: string): React.ReactNode[] =>
    nodes.map((node, position) => {
      const key = `${keyPrefix}-${position}`;
      if (node.type === "text") return <Fragment key={key}>{node.text}</Fragment>;
      if (node.type === "code") {
        return (
          <code key={key} className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]">
            {node.text}
          </code>
        );
      }
      if (node.type === "bold") {
        return (
          <strong key={key} className="font-semibold">
            {renderInline(node.children, key)}
          </strong>
        );
      }

      const source = byIndex.get(node.index);
      return source ? (
        <button
          key={`cite-${node.offset}`}
          type="button"
          onClick={() => onOpenSource(source)}
          title={source.title}
          aria-label={`근거 ${node.index}: ${source.title} 열기`}
          className="mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded bg-primary/10 px-1 align-super text-xs font-medium text-primary transition-colors hover:bg-primary/20"
        >
          {node.index}
        </button>
      ) : (
        <Fragment key={`cite-${node.offset}`}>{node.raw}</Fragment>
      );
    });

  // 진행 표시는 마지막 글자 바로 뒤에 붙어야 하므로 마지막 블록 안에 넣습니다.
  const caret = streaming ? (
    <span
      aria-hidden
      className="ml-0.5 inline-block h-[1em] w-0.5 translate-y-0.5 animate-pulse rounded-full bg-foreground/50"
    />
  ) : null;

  return (
    <div
      className={cn(
        "min-w-0 space-y-2 text-sm leading-relaxed [overflow-wrap:anywhere] break-words",
        className,
      )}
    >
      {blocks.map((block, blockIndex) => {
        const isLast = blockIndex === blocks.length - 1;
        if (block.type === "paragraph") {
          return (
            <p key={blockIndex} className="whitespace-pre-wrap">
              {renderInline(block.children, `p${blockIndex}`)}
              {isLast ? caret : null}
            </p>
          );
        }
        const List = block.ordered ? "ol" : "ul";
        return (
          <List
            key={blockIndex}
            start={block.ordered ? block.start : undefined}
            className={cn("space-y-1 pl-5", block.ordered ? "list-decimal" : "list-disc")}
          >
            {block.items.map((item, itemIndex) => (
              <li key={itemIndex}>
                {renderInline(item, `l${blockIndex}-${itemIndex}`)}
                {isLast && itemIndex === block.items.length - 1 ? caret : null}
              </li>
            ))}
          </List>
        );
      })}
      {blocks.length === 0 ? caret : null}
    </div>
  );
}
