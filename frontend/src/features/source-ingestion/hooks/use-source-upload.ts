"use client";

import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

import { useApi } from "@/lib/api/context";
import type { MeetingUtterance, ProcessingJob, TranscriptSourceInput } from "@/lib/api";

import { validateDocuments } from "../lib/validate-file";

export type UploadItemStatus = "uploading" | "uploaded" | "failed";

export type UploadItem = {
  id: string;
  fileName: string;
  sizeBytes: number;
  status: UploadItemStatus;
  /** 전송 진행률 0..1 */
  progress: number;
  /** 회의 녹음일 때만. 크기 대신 길이를 보여줍니다. */
  durationSeconds?: number;
  job?: ProcessingJob;
  errorMessage?: string;
};

function recordingName(): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `회의 녹음 ${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

/**
 * 소스 업로드 큐를 관리합니다.
 *
 * 문서와 회의 녹음이 같은 큐를 쓰므로 진행률 표시와 처리 단계 폴링을
 * 한 곳에서 이어받습니다. 전송이 끝나면 서버가 준 job이 항목에 붙습니다.
 */
export function useSourceUpload(workspaceId: string, onUploaded?: () => void) {
  const api = useApi();
  const [items, setItems] = useState<UploadItem[]>([]);
  const sequence = useRef(0);

  const patch = useCallback((id: string, changes: Partial<UploadItem>) => {
    setItems((current) => current.map((item) => (item.id === id ? { ...item, ...changes } : item)));
  }, []);

  const enqueue = useCallback(
    (fileName: string, sizeBytes: number, durationSeconds?: number): UploadItem => {
      const item: UploadItem = {
        id: `upload-${++sequence.current}`,
        fileName,
        sizeBytes,
        durationSeconds,
        status: "uploading",
        progress: 0,
      };
      setItems((current) => [item, ...current]);
      return item;
    },
    [],
  );

  const uploadDocuments = useCallback(
    async (files: File[]) => {
      const { accepted, rejected } = validateDocuments(files);

      for (const { file, reason } of rejected) {
        toast.error(`${file.name}: ${reason}`);
      }
      if (accepted.length === 0) return;

      const queued = accepted.map((file) => enqueue(file.name, file.size));

      const results = await Promise.allSettled(
        accepted.map((file, index) =>
          api.uploadDocument(workspaceId, file, {
            onProgress: (ratio) => patch(queued[index].id, { progress: ratio }),
          }),
        ),
      );

      let uploaded = 0;
      results.forEach((result, index) => {
        const item = queued[index];
        if (result.status === "fulfilled") {
          uploaded += 1;
          patch(item.id, { status: "uploaded", progress: 1, job: result.value });
        } else {
          const reason = result.reason;
          patch(item.id, {
            status: "failed",
            errorMessage: reason instanceof Error ? reason.message : "업로드에 실패했습니다.",
          });
          toast.error(`${item.fileName} 업로드에 실패했습니다.`);
        }
      });

      if (uploaded > 0) {
        toast.success(`${uploaded}개 파일을 올렸습니다. 분석을 시작합니다.`);
        onUploaded?.();
        window.dispatchEvent(new Event("maeglagi:sources-changed"));
      }
    },
    [workspaceId, patch, enqueue, onUploaded, api],
  );

  /** 녹음이 끝나는 즉시 호출됩니다. 사용자가 따로 업로드를 누르지 않습니다. */
  const uploadRecording = useCallback(
    async (audio: Blob, durationSeconds: number, liveDraft?: { utterances: MeetingUtterance[] }, projectId?: string, projectIds?: string[]) => {
      if (audio.size === 0) {
        toast.error("녹음된 오디오가 없습니다.");
        throw new Error("녹음된 오디오가 없습니다.");
      }

      const item = enqueue(typeof File !== "undefined" && audio instanceof File ? audio.name : recordingName(), audio.size, durationSeconds || undefined);

      try {
        const job = await api.uploadRecording(workspaceId, audio, liveDraft, projectId, {
          onProgress: (ratio) => patch(item.id, { progress: ratio }),
          projectIds,
        });
        patch(item.id, { status: "uploaded", progress: 1, job });
        toast.success("녹음을 올렸습니다. 음성 인식 후 대본 검토가 필요합니다.");
        onUploaded?.();
        window.dispatchEvent(new Event("maeglagi:sources-changed"));
      } catch (error) {
        patch(item.id, {
          status: "failed",
          errorMessage: error instanceof Error ? error.message : "업로드에 실패했습니다.",
        });
        toast.error("녹음 업로드에 실패했습니다.");
        throw error;
      }
    },
    [workspaceId, patch, enqueue, onUploaded, api],
  );

  const uploadTranscript = useCallback(
    async (input: TranscriptSourceInput, projectId?: string) => {
      if (!input.text.trim()) return false;
      const item = enqueue(
        input.title || "회의 대본",
        new Blob([input.text]).size,
        input.durationSeconds,
      );
      try {
        const job = await api.uploadTranscript(workspaceId, { ...input, projectId: projectId || null, projectIds: input.projectIds ?? (projectId ? [projectId] : []) });
        patch(item.id, { status: "uploaded", progress: 1, job });
        onUploaded?.();
        window.dispatchEvent(new Event("maeglagi:sources-changed"));
        toast.success("대본 초안을 올렸습니다. 검토 후 확인해 주세요.");
        return true;
      } catch (error) {
        patch(item.id, {
          status: "failed",
          errorMessage: error instanceof Error ? error.message : "업로드 실패",
        });
        toast.error("대본을 올리지 못했습니다. 편집 내용은 유지됩니다.");
        return false;
      }
    },
    [workspaceId, enqueue, patch, onUploaded, api],
  );

  const dismiss = useCallback((id: string) => {
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  return { items, uploadDocuments, uploadRecording, uploadTranscript, dismiss };
}
