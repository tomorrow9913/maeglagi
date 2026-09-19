"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Mic, Minus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { useSourceUpload } from "../hooks/use-source-upload";
import { useJobEvents } from "../hooks/use-job-events";
import { MeetingCapture } from "./meeting-capture";
import { MeetingReviewDialog } from "./meeting-review-dialog";
import { SourceFileUpload } from "./source-file-upload";
import { UploadQueue } from "./upload-queue";
import type { ProcessingJob } from "@/lib/api";

export function SourceUploadDialog({ workspaceId, mode, onClose, onRecordingBusyChange }: {
  workspaceId: string;
  mode: "document" | "meeting" | null;
  onClose: () => void;
  onRecordingBusyChange?: (busy: boolean) => void;
}) {
  const { items, uploadDocuments, uploadRecording, uploadTranscript, dismiss } = useSourceUpload(workspaceId);
  const [recordingBusy, setRecordingBusy] = useState(false);
  const [meetingMounted, setMeetingMounted] = useState(mode === "meeting");
  const [reviewSourceId, setReviewSourceId] = useState<string>();
  const [restartKey, setRestartKey] = useState(0);
  const uploading = items.some((item) => item.status === "uploading");
  useEffect(() => { if (mode === "meeting") setMeetingMounted(true); }, [mode]);
  useEffect(() => { onRecordingBusyChange?.(recordingBusy); }, [recordingBusy, onRecordingBusyChange]);

  const settled = useCallback((job: ProcessingJob) => {
    if (job.status === "awaiting_agent") {
      toast.info("소스가 저장됐습니다. 에이전트 분석을 기다립니다.");
    } else if (job.status === "awaiting_review") {
      toast.info("대본 검토가 준비됐습니다.", { action: { label: "검토 열기", onClick: () => setReviewSourceId(job.sourceId) } });
    } else if (job.status === "failed") {
      toast.error(job.sourceKind === "meeting" ? "회의 처리에 실패했습니다. 저장된 녹음이나 대본을 확인해 주세요." : "소스 분석에 실패했습니다. 소스에서 상태를 확인해 주세요.",
        job.sourceKind === "meeting" ? { action: { label: "대본 열기", onClick: () => setReviewSourceId(job.sourceId) } } : undefined);
    } else toast.success("소스 분석이 완료됐습니다. Ask에서 질문해 보세요.");
  }, []);
  const jobs = useJobEvents(workspaceId, items.flatMap((item) => item.job ? [item.job] : []), settled, restartKey);
  return (
    <>
      <Dialog open={mode === "document"} onOpenChange={(open) => { if (!open && !uploading) onClose(); }}>
        <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-2xl" showCloseButton={!uploading}
          onInteractOutside={(event) => { if (uploading) event.preventDefault(); }}
          onEscapeKeyDown={(event) => { if (uploading) event.preventDefault(); }}>
          <DialogHeader>
            <DialogTitle>문서·녹음 파일 업로드</DialogTitle>
            <DialogDescription>이 화면의 업로드는 서비스 AI 연결로 자동 처리합니다. 에이전트로 처리하려면 계정 MCP 연결을 사용하세요.</DialogDescription>
          </DialogHeader>
          <SourceFileUpload workspaceId={workspaceId} onDocuments={uploadDocuments} onAudio={uploadRecording} />
          <UploadQueue items={items} jobs={jobs} onDismiss={dismiss} onReview={setReviewSourceId} />
          {!uploading && <Button variant="outline" onClick={onClose}>Ask로 돌아가기</Button>}
        </DialogContent>
      </Dialog>
      {meetingMounted && <aside aria-label="회의 녹음 패널" className={mode === "meeting"
        ? "fixed inset-x-2 bottom-2 z-40 max-h-[55dvh] overflow-y-auto rounded-xl border bg-background p-4 shadow-xl sm:inset-x-auto sm:right-4 sm:w-[min(42rem,calc(100vw-2rem))] sm:max-h-[80dvh]"
        : "fixed right-3 bottom-[calc(7rem+env(safe-area-inset-bottom))] z-40 max-w-[calc(100vw-1.5rem)] rounded-full border bg-background p-1 shadow-lg sm:bottom-28"}>
        {mode === "meeting" ? <div className="mb-3 flex items-center justify-between gap-2">
          <div><h2 className="text-sm font-semibold">회의 녹음 및 받아쓰기</h2><p className="text-xs text-muted-foreground">녹음 중에도 Ask에서 저장된 소스를 질문할 수 있습니다.</p></div>
          <Button type="button" size="sm" variant="outline" onClick={onClose} aria-label="회의 패널 접기"><Minus className="size-4" /> 접기</Button>
        </div> : <Button type="button" size="sm" variant="ghost" onClick={() => window.dispatchEvent(new CustomEvent("maeglagi:open-source-upload", { detail: { workspaceId, mode: "meeting" } }))} aria-label="회의 패널 다시 열기">
          <Mic className="size-4" /> {recordingBusy ? "녹음·초안 진행 중 · 열기" : "회의 패널 열기"}
        </Button>}
        <div className={mode === "meeting" ? "" : "hidden"} aria-hidden={mode !== "meeting"}>
          <MeetingCapture workspaceId={workspaceId} onAudio={uploadRecording} onTranscript={uploadTranscript} onBusyChange={setRecordingBusy} />
          <UploadQueue items={items} jobs={jobs} onDismiss={dismiss} onReview={setReviewSourceId} className="mt-4" />
        </div>
      </aside>}
      <MeetingReviewDialog workspaceId={workspaceId} sourceId={reviewSourceId} onClose={() => setReviewSourceId(undefined)} onRetried={() => setRestartKey((value) => value + 1)} onConfirmed={() => { setRestartKey((value) => value + 1); window.dispatchEvent(new Event("maeglagi:sources-changed")); }} />
    </>
  );
}
