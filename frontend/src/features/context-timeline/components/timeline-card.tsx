"use client";

import { ArrowRight, FileText, Mic } from "lucide-react";

import { StatusBadge, type StatusTone } from "@/components/common/status-badge";
import type { ContextItem, ContextItemSource } from "@/lib/api";
import { cn } from "@/lib/utils";
import { contextKindLabel, type ContextKind } from "@/types/context";

const kindTone: Record<ContextKind, StatusTone> = {
  decision: "success",
  issue: "danger",
  task: "info",
  event: "neutral",
};

function formatTime(iso: string): string {
  return iso.slice(11, 16);
}

/**
 * Context Timeline의 한 항목입니다.
 *
 * 근거 소스를 누르면 원문의 해당 구간으로, 대체된 항목이면 대체한 결정으로
 * 이동합니다.
 */
export function TimelineCard({
  item,
  supersededByTitle,
  onOpenSource,
  onOpenSuperseder,
  className,
}: {
  item: ContextItem;
  /** 대체한 항목의 제목. 있으면 이동 버튼을 보여줍니다. */
  supersededByTitle?: string;
  onOpenSource: (source: ContextItemSource) => void;
  onOpenSuperseder?: (contextItemId: string) => void;
  className?: string;
}) {
  const isSuperseded = Boolean(item.supersededBy);

  return (
    <article
      className={cn(
        "rounded-xl border border-border bg-card p-4",
        isSuperseded && "opacity-75",
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
          {formatTime(item.occurredAt)}
        </time>
      </div>

      <h3 className={cn("mt-3 font-medium", isSuperseded && "line-through")}>{item.title}</h3>
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
