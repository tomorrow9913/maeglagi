"use client";

import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import type { ProcessingJob } from "@/lib/api";

import { validateDocuments } from "../lib/validate-file";

export type UploadItemStatus = "uploading" | "uploaded" | "failed";

export type UploadItem = {
  id: string;
  fileName: string;
  sizeBytes: number;
  status: UploadItemStatus;
  /** 전송 진행률 0..1 */
  progress: number;
  job?: ProcessingJob;
  errorMessage?: string;
};

/**
 * 문서 업로드 큐를 관리합니다.
 *
 * 파일 여러 개를 동시에 올리고 각각의 전송 진행률을 따로 추적합니다.
 * 전송이 끝나면 서버가 준 job이 붙고, 이후 처리 진행률은 폴링이 이어받습니다.
 */
export function useDocumentUpload(workspaceId: string, onUploaded?: () => void) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const sequence = useRef(0);

  const patch = useCallback((id: string, changes: Partial<UploadItem>) => {
    setItems((current) => current.map((item) => (item.id === id ? { ...item, ...changes } : item)));
  }, []);

  const upload = useCallback(
    async (files: File[]) => {
      const { accepted, rejected } = validateDocuments(files);

      for (const { file, reason } of rejected) {
        toast.error(`${file.name}: ${reason}`);
      }
      if (accepted.length === 0) return;

      const queued: UploadItem[] = accepted.map((file) => ({
        id: `upload-${++sequence.current}`,
        fileName: file.name,
        sizeBytes: file.size,
        status: "uploading",
        progress: 0,
      }));
      setItems((current) => [...queued, ...current]);

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
      }
    },
    [workspaceId, patch, onUploaded],
  );

  const dismiss = useCallback((id: string) => {
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  return { items, upload, dismiss };
}
