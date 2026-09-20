import { ChevronRight, FileText, Mic } from "lucide-react";

import { StatusBadge } from "@/components/common/status-badge";
import type { Source } from "@/lib/api";

import { formatBytes } from "../lib/format";
import { sourcePresentation } from "../lib/source-presentation";

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
        const presentation = sourcePresentation(source.status, source.kind);

        return (
          <li key={source.id}>
            <button
              type="button"
              onClick={() => onOpen(source.id)}
              disabled={!presentation.canOpen}
              className="flex w-full items-center gap-3 p-4 text-left transition-colors hover:bg-accent/40 disabled:cursor-default disabled:hover:bg-transparent"
            >
              <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{source.title}</p>
                <p className="text-xs text-muted-foreground">
                  {[detailOf(source), source.createdAt.slice(0, 10)].filter(Boolean).join(" · ")}
                </p>
              </div>
              <StatusBadge tone={presentation.tone}>
                {presentation.label}{progress?.[source.id] !== undefined && presentation.isProcessing ? ` · ${Math.round(progress[source.id] * 100)}%` : ""}
              </StatusBadge>
              {presentation.canOpen ? (
                <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              ) : null}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
