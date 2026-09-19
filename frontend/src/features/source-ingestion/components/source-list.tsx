import { ChevronRight, FileText, Mic } from "lucide-react";

import { StatusBadge, type StatusTone } from "@/components/common/status-badge";
import type { Source } from "@/lib/api";
import { processingStatusLabel, type ProcessingStatus } from "@/types/context";

import { formatBytes } from "../lib/format";

const statusTone: Record<ProcessingStatus, StatusTone> = {
  queued: "neutral",
  enqueue_pending: "info",
  processing: "info",
  awaiting_review: "warning",
  succeeded: "success",
  failed: "danger",
};

function detailOf(source: Source): string {
  if (source.kind === "meeting" && source.durationSeconds !== undefined) {
    const minutes = Math.round(source.durationSeconds / 60);
    return `${minutes}분 녹음`;
  }
  return source.sizeBytes !== undefined ? formatBytes(source.sizeBytes) : "";
}

/** 워크스페이스에 올라온 소스 목록입니다. 항목을 누르면 원문이 열립니다. */
export function SourceList({
  sources,
  progress,
  onOpen,
}: {
  sources: Source[];
  progress?: Record<string, number>;
  onOpen: (sourceId: string) => void;
}) {
  return (
    <ul className="divide-y divide-border rounded-xl border border-border bg-card">
      {sources.map((source) => {
        const Icon = source.kind === "meeting" ? Mic : FileText;

        return (
          <li key={source.id}>
            <button
              type="button"
              onClick={() => onOpen(source.id)}
              disabled={source.status !== "succeeded" && source.status !== "awaiting_review" && !(source.kind === "meeting" && source.status === "failed")}
              className="flex w-full items-center gap-3 p-4 text-left transition-colors hover:bg-accent/40 disabled:cursor-default disabled:hover:bg-transparent"
            >
              <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{source.title}</p>
                <p className="text-xs text-muted-foreground">
                  {[detailOf(source), source.createdAt.slice(0, 10)].filter(Boolean).join(" · ")}
                </p>
              </div>
              <StatusBadge tone={statusTone[source.status]}>
                {processingStatusLabel[source.status]}{progress?.[source.id] !== undefined && (source.status === "processing" || source.status === "queued" || source.status === "enqueue_pending") ? ` · ${Math.round(progress[source.id] * 100)}%` : ""}
              </StatusBadge>
              {source.status === "succeeded" || source.status === "awaiting_review" || (source.kind === "meeting" && source.status === "failed") ? (
                <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              ) : null}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
