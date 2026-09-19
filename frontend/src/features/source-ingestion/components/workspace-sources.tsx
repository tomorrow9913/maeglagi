"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { FileText, Plus, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAsync } from "@/hooks/use-async";
import { api } from "@/lib/api";
import { workspacePath } from "@/lib/navigation";
import { SourceViewer } from "./source-viewer";
import { SourceUploadDialog } from "./source-upload-dialog";

export function WorkspaceSources({ workspaceId }: { workspaceId: string }) {
  const { data, error, isLoading, reload } = useAsync(
    (signal) => api.listSources(workspaceId, signal),
    [workspaceId],
  );
  const [viewer, setViewer] = useState<string>();
  const [mode, setMode] = useState<"document" | "meeting" | null>(null);
  useEffect(() => {
    window.addEventListener("maeglagi:sources-changed", reload);
    return () => window.removeEventListener("maeglagi:sources-changed", reload);
  }, [reload]);
  return (
    <section className="mt-5 border-t pt-4" aria-label="워크스페이스 소스">
      <div className="mb-2 flex items-center justify-between px-2">
        <Link href={workspacePath(workspaceId, "sources")} className="text-xs font-medium">
          소스 {data ? `(${data.length})` : ""}
        </Link>
        <Button
          type="button"
          size="icon-xs"
          variant="ghost"
          title="파일 추가"
          aria-label="파일 추가"
          onClick={() => setMode("document")}
        >
          <Plus aria-hidden />
        </Button>
      </div>
      {isLoading && <p className="px-2 text-xs text-muted-foreground">불러오는 중…</p>}
      {error && (
        <Button size="sm" variant="ghost" onClick={reload}>
          <RefreshCw />
          소스 다시 불러오기
        </Button>
      )}
      {!isLoading && !error && !data?.length && (
        <p className="px-2 text-xs text-muted-foreground">질문의 근거가 될 소스를 추가하세요.</p>
      )}
      <ul className="max-h-[45dvh] space-y-1 overflow-y-auto">
        {data?.map((source) => (
          <li key={source.id}>
            <button
              type="button"
              onClick={() => setViewer(source.id)}
              className="flex w-full items-start gap-2 rounded-md px-2 py-2 text-left text-xs hover:bg-accent"
            >
              <FileText className="mt-0.5 size-3 shrink-0" aria-hidden />
              <span className="min-w-0">
                <span className="line-clamp-2">{source.title}</span>
                <span className="text-muted-foreground">
                  {source.status === "succeeded"
                    ? "분석 완료"
                    : source.status === "failed"
                      ? "처리 실패"
                      : "처리 중"}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      <SourceViewer sourceId={viewer} onClose={() => setViewer(undefined)} />
      <SourceUploadDialog workspaceId={workspaceId} mode={mode} onClose={() => setMode(null)} />
    </section>
  );
}
