import { StatusBadge, type StatusTone } from "@/components/common/status-badge";
import { cn } from "@/lib/utils";
import { contextKindLabel, type ContextKind } from "@/types/context";

export type TimelineCardProps = {
  kind: ContextKind;
  title: string;
  summary?: string;
  /** ISO-8601 문자열 */
  occurredAt: string;
  /** 근거가 된 소스 이름 */
  sourceLabel?: string;
  /** 이후 결정으로 대체된 항목인지 여부 (Temporal 규칙) */
  superseded?: boolean;
  className?: string;
};

const kindTone: Record<ContextKind, StatusTone> = {
  decision: "success",
  issue: "danger",
  task: "info",
  event: "neutral",
};

/**
 * Context Timeline의 한 항목입니다.
 *
 * 데이터 연결과 목록 가상화는 Day 3 Timeline 작업에서 붙입니다.
 */
export function TimelineCard({
  kind,
  title,
  summary,
  occurredAt,
  sourceLabel,
  superseded = false,
  className,
}: TimelineCardProps) {
  return (
    <article
      className={cn(
        "rounded-xl border border-border bg-card p-4",
        superseded && "opacity-60",
        className,
      )}
    >
      <div className="flex items-center gap-2">
        <StatusBadge tone={kindTone[kind]}>{contextKindLabel[kind]}</StatusBadge>
        {superseded ? <StatusBadge tone="warning">대체됨</StatusBadge> : null}
        <time dateTime={occurredAt} className="ml-auto text-xs text-muted-foreground">
          {occurredAt.slice(0, 10)}
        </time>
      </div>
      <h3 className={cn("mt-3 font-medium", superseded && "line-through")}>{title}</h3>
      {summary ? (
        <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{summary}</p>
      ) : null}
      {sourceLabel ? (
        <p className="mt-3 text-xs text-muted-foreground">근거: {sourceLabel}</p>
      ) : null}
    </article>
  );
}
