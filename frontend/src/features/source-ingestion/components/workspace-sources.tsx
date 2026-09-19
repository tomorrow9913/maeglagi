"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronDown, FileText, FileUp, Mic, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useDemoMode, useWorkspacePath } from "@/lib/api/context";
import { useLiveSources } from "../hooks/use-live-sources";
import { SourceViewer } from "./source-viewer";
import { SourceUploadDialog } from "./source-upload-dialog";
import { MeetingReviewDialog } from "./meeting-review-dialog";

export function WorkspaceSources({ workspaceId }: { workspaceId: string }) {
  const isDemo = useDemoMode();
  const workspacePath = useWorkspacePath();
  const { sources: data, progress, error, isLoading, reload } = useLiveSources(workspaceId);
  const [viewer, setViewer] = useState<string>();
  const [reviewSourceId, setReviewSourceId] = useState<string>();
  const [mode, setMode] = useState<"document" | "meeting" | null>(null);
  const [recordingBusy, setRecordingBusy] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  useEffect(() => {
    const openUpload = (event: Event) => {
      const detail = (event as CustomEvent<{ workspaceId: string; mode: "document" | "meeting" }>)
        .detail;
      if (detail?.workspaceId === workspaceId) setMode(recordingBusy && detail.mode === "document" ? "meeting" : detail.mode);
    };
    window.addEventListener("maeglagi:open-source-upload", openUpload);
    return () => window.removeEventListener("maeglagi:open-source-upload", openUpload);
  }, [workspaceId, recordingBusy]);
  return (
    <section
      className="mt-5 rounded-lg border p-3 md:rounded-none md:border-0 md:border-t md:px-0 md:pt-4"
      aria-label="워크스페이스 소스"
    >
      <button
        type="button"
        className="flex w-full items-center justify-between text-left text-sm font-semibold md:hidden"
        aria-expanded={mobileOpen}
        aria-controls="workspace-source-panel"
        onClick={() => setMobileOpen((open) => !open)}
      >
        <span>질문 근거 · 소스 {data ? `(${data.length})` : ""}</span>
        <ChevronDown
          className={`size-4 transition-transform ${mobileOpen ? "rotate-180" : ""}`}
          aria-hidden
        />
      </button>
      <div id="workspace-source-panel" className={mobileOpen ? "mt-3 md:mt-0" : "hidden md:block"}>
        <div className="mb-3 flex items-center justify-between px-1">
          <h2 className="text-sm font-semibold">질문 근거 · 소스</h2>
          <Link
            href={workspacePath(workspaceId, "sources")}
            className="text-xs text-muted-foreground underline-offset-2 hover:underline"
          >
            전체 보기
          </Link>
        </div>
        {!isDemo && <div className="mb-3 grid grid-cols-2 gap-1.5">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={recordingBusy}
            className="gap-1 px-2 text-xs"
            onClick={() => setMode("document")}
          >
            <FileUp className="size-3.5" aria-hidden />
            문서·녹음 파일
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="gap-1 px-2 text-xs"
            onClick={() => setMode("meeting")}
          >
            <Mic className="size-3.5" aria-hidden />
            회의 추가
          </Button>
        </div>}
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
                onClick={() => !isDemo && (source.status === "awaiting_review" || (source.kind === "meeting" && source.status === "failed")) ? setReviewSourceId(source.id) : setViewer(source.id)}
                className="flex w-full items-start gap-2 rounded-md px-2 py-2 text-left text-xs hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring"
              >
                <FileText className="mt-0.5 size-3 shrink-0" aria-hidden />
                <span className="min-w-0">
                  <span className="line-clamp-2">{source.title}</span>
                  <span className="text-muted-foreground">
                    {source.status === "succeeded"
                      ? "분석 완료"
                      : source.status === "failed"
                        ? "처리 실패"
                        : source.status === "awaiting_review"
                          ? "대본 검토 필요 · 열기"
                        : `처리 중${progress[source.id] !== undefined ? ` · ${Math.round(progress[source.id] * 100)}%` : ""}`}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      <SourceViewer workspaceId={workspaceId} sourceId={viewer} onClose={() => setViewer(undefined)} />
      {!isDemo && <SourceUploadDialog workspaceId={workspaceId} mode={mode} onClose={() => setMode(null)} onRecordingBusyChange={setRecordingBusy} />}
      {!isDemo && <MeetingReviewDialog workspaceId={workspaceId} sourceId={reviewSourceId} onClose={() => setReviewSourceId(undefined)} onConfirmed={() => { reload(); window.dispatchEvent(new Event("maeglagi:sources-changed")); }} />}
    </section>
  );
}
