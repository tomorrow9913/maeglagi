import { ChevronRight, FileText, Mic } from "lucide-react";

import { StatusBadge } from "@/components/common/status-badge";
import type { Source } from "@/lib/api";
import { localDateKey } from "@/lib/format-date";

import { FAILED_DOCUMENT_HINT } from "../lib/copy";
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
        // 실패한 문서는 열어볼 원문도, 서버에 다시 시도할 방법도 없습니다. 목록 응답에 실패 사유가
        // 없으므로 다음에 할 수 있는 일(같은 파일 다시 올리기)만 알려줍니다.
        const failedDocument = source.status === "failed" && !presentation.canOpen;
        const body = (
          <>
            <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{source.title}</p>
              <p className="text-xs text-muted-foreground">
                {[detailOf(source), localDateKey(source.createdAt)].filter(Boolean).join(" · ")}
              </p>
              {failedDocument ? <p className="mt-1 text-xs text-destructive">{FAILED_DOCUMENT_HINT}</p> : null}
            </div>
            <StatusBadge tone={presentation.tone}>
              {presentation.label}{progress?.[source.id] !== undefined && presentation.isProcessing ? ` · ${Math.round(progress[source.id] * 100)}%` : ""}
            </StatusBadge>
            {presentation.canOpen ? (
              <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            ) : null}
          </>
        );

        return (
          <li key={source.id}>
            {presentation.canOpen ? (
              <button
                type="button"
                onClick={() => onOpen(source.id)}
                className="flex w-full items-center gap-3 p-4 text-left transition-colors hover:bg-accent/40"
              >
                {body}
              </button>
            ) : (
              // 아직 열 수 없는 항목은 비활성 버튼 대신 일반 행으로 두어 안내 문구가 흐려지지 않게 합니다.
              <div className="flex w-full items-center gap-3 p-4">{body}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
