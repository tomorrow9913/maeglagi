"use client";

import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { useSourceUpload } from "../hooks/use-source-upload";
import { useJobPolling } from "../hooks/use-job-polling";
import { MeetingCapture } from "./meeting-capture";
import { UploadDropzone } from "./upload-dropzone";
import { UploadQueue } from "./upload-queue";
import type { ProcessingJob } from "@/lib/api";

export function SourceUploadDialog({
  workspaceId,
  mode,
  onClose,
}: {
  workspaceId: string;
  mode: "document" | "meeting" | null;
  onClose: () => void;
}) {
  const { items, uploadDocuments, uploadRecording, uploadTranscript, dismiss } =
    useSourceUpload(workspaceId);
  const [recordingBusy, setRecordingBusy] = useState(false);
  const busy = recordingBusy || items.some((item) => item.status === "uploading");
  const ids = useMemo(() => items.flatMap((item) => (item.job ? [item.job.id] : [])), [items]);
  const settled = useCallback((job: ProcessingJob) => {
    window.dispatchEvent(new Event("maeglagi:sources-changed"));
    if (job.status === "failed")
      toast.error("소스 분석에 실패했습니다. 소스에서 상태를 확인해 주세요.");
    else toast.success("소스 분석이 완료됐습니다. Ask에서 질문해 보세요.");
  }, []);
  const jobs = useJobPolling(ids, settled);
  return (
    <Dialog
      open={mode !== null}
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
    >
      <DialogContent
        className="max-h-[85dvh] overflow-y-auto sm:max-w-2xl"
        showCloseButton={!busy}
        onInteractOutside={(event) => {
          if (busy) event.preventDefault();
        }}
        onEscapeKeyDown={(event) => {
          if (busy) event.preventDefault();
        }}
      >
        <DialogHeader>
          <DialogTitle>{mode === "meeting" ? "회의 녹음 및 받아쓰기" : "파일 업로드"}</DialogTitle>
          <DialogDescription>
            이 워크스페이스에 소스를 추가하고 Ask에서 이어서 질문하세요.
          </DialogDescription>
        </DialogHeader>
        {mode === "meeting" ? (
          <MeetingCapture
            onAudio={uploadRecording}
            onTranscript={uploadTranscript}
            onBusyChange={setRecordingBusy}
          />
        ) : (
          <UploadDropzone onFilesSelected={uploadDocuments} />
        )}
        <UploadQueue items={items} jobs={jobs} onDismiss={dismiss} />
        {busy ? (
          <p className="text-xs text-muted-foreground">
            진행 중인 녹음·업로드를 마치고, 대본을 업로드하거나 버리면 닫을 수 있습니다.
          </p>
        ) : (
          <Button variant="outline" onClick={onClose}>
            Ask로 돌아가기
          </Button>
        )}
      </DialogContent>
    </Dialog>
  );
}
