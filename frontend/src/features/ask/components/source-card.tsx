import { FileText, Mic } from "lucide-react";

import { cn } from "@/lib/utils";
import type { SourceKind } from "@/lib/api";

import { formatSourceMeta } from "../lib/source-meta";

export type SourceCardProps = {
  /** 답변에서 [1], [2]로 참조하는 번호 */
  index: number;
  kind: SourceKind;
  title: string;
  /** 근거로 인용된 원문 일부 */
  excerpt?: string;
  /** 회의 근거가 시작되는 시각(초). 문서 근거에는 없습니다. */
  timestamp?: number;
  onOpen?: () => void;
  className?: string;
};

/**
 * Ask 답변의 근거 카드입니다.
 *
 * 답변 본문의 인용 번호와 1:1로 대응하며, 누르면 원문의 해당 구간으로
 * 이동합니다. 회의인지 문서인지는 아이콘만으로 전하지 않고 글자로도 적습니다.
 */
export function SourceCard({
  index,
  kind,
  title,
  excerpt,
  timestamp,
  onOpen,
  className,
}: SourceCardProps) {
  const Icon = kind === "meeting" ? Mic : FileText;

  return (
    <button
      type="button"
      onClick={onOpen}
      disabled={!onOpen}
      className={cn(
        "w-full rounded-xl border border-border bg-card p-4 text-left transition-colors",
        onOpen && "hover:border-foreground/30",
        className,
      )}
    >
      <div className="flex items-center gap-2">
        <span className="flex size-5 shrink-0 items-center justify-center rounded bg-muted text-xs font-medium text-muted-foreground tabular-nums">
          {index}
        </span>
        <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{title}</span>
        <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
          {formatSourceMeta(kind, timestamp)}
        </span>
      </div>
      {excerpt ? (
        <p className="mt-2 line-clamp-3 text-sm leading-relaxed [overflow-wrap:anywhere] break-words text-muted-foreground">
          {excerpt}
        </p>
      ) : null}
    </button>
  );
}
