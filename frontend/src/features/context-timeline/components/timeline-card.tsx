"use client";

import { ArrowRight, FileText, Mic } from "lucide-react";

import { StatusBadge } from "@/components/common/status-badge";
import type { ContextItem, ContextItemSource } from "@/lib/api";
import { localTime } from "@/lib/format-date";
import { cn } from "@/lib/utils";
import { contextKindLabel } from "@/types/context";

import { kindTone } from "../lib/kind-style";

/**
 * Context Timeline의 한 항목입니다.
 *
 * 근거 소스를 누르면 원문의 해당 구간으로, 대체된 항목이면 대체한 결정으로
 * 이동합니다.
 */
export function TimelineCard({
  item,
  supersededByTitle,
  isHighlighted = false,
  onOpenSource,
  onOpenSuperseder,
  className,
}: {
  item: ContextItem;
  /** 대체한 항목의 제목. 있으면 이동 버튼을 보여줍니다. */
  supersededByTitle?: string;
  /** "이후 결정"으로 방금 이동해 온 카드. 어디로 왔는지 잠깐 표시합니다. */
  isHighlighted?: boolean;
  onOpenSource: (source: ContextItemSource) => void;
  onOpenSuperseder?: (contextItemId: string) => void;
  className?: string;
}) {
  const isSuperseded = Boolean(item.supersededBy);
  // 유효한 결정은 타임라인에서 가장 먼저 눈에 들어와야 하는 항목입니다.
  const isActiveDecision = item.kind === "decision" && !isSuperseded;

  return (
    <article
      // "이후 결정" 이동이 초점을 여기로 옮깁니다. Tab 순서에는 넣지 않습니다.
      tabIndex={-1}
      data-timeline-card
      className={cn(
        "rounded-xl border border-border bg-card p-4 transition-shadow outline-none focus-visible:ring-3 focus-visible:ring-ring/50 motion-reduce:transition-none",
        isActiveDecision && "border-success/35 shadow-xs",
        isHighlighted && "border-primary ring-3 ring-primary/40",
        className,
      )}
    >
      <div className="flex items-center gap-2">
        <StatusBadge tone={kindTone[item.kind]}>{contextKindLabel[item.kind]}</StatusBadge>
        {isSuperseded ? <StatusBadge tone="warning">대체됨</StatusBadge> : null}
        <time
          dateTime={item.occurredAt}
          className="ml-auto text-xs text-muted-foreground tabular-nums"
        >
          {localTime(item.occurredAt)}
        </time>
      </div>

      <h3
        className={cn(
          "mt-3 font-medium",
          isActiveDecision && "font-semibold",
          // 카드 전체를 흐리게 하면 "이후 결정" 링크까지 대비가 떨어지므로 제목만 누그러뜨립니다.
          isSuperseded && "text-muted-foreground line-through",
        )}
      >
        {item.title}
      </h3>
      <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{item.summary}</p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {item.sources.map((source) => {
          const Icon = source.kind === "meeting" ? Mic : FileText;
          return (
            <button
              key={source.id}
              type="button"
              onClick={() => onOpenSource(source)}
              className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
            >
              <Icon className="size-3 shrink-0" aria-hidden />
              <span className="truncate">{source.title}</span>
            </button>
          );
        })}
      </div>

      {isSuperseded && supersededByTitle ? (
        <button
          type="button"
          onClick={() => onOpenSuperseder?.(item.supersededBy!)}
          className="mt-3 inline-flex items-center gap-1.5 text-xs text-warning transition-opacity hover:opacity-80"
        >
          <ArrowRight className="size-3" aria-hidden />
          이후 결정: {supersededByTitle}
        </button>
      ) : null}
    </article>
  );
}
