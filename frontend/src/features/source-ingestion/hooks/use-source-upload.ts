"use client";

import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

import { useApi } from "@/lib/api/context";
import type { MeetingUtterance, ProcessingJob, TranscriptSourceInput } from "@/lib/api";
import { toUserMessage } from "@/lib/api/error-message";

import { RECORDING_UPLOAD_FAILED, UPLOAD_FAILED } from "../lib/copy";
import { validateDocuments } from "../lib/validate-file";

export type UploadItemStatus = "uploading" | "uploaded" | "failed" | "cancelled";

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
  /** 문서 업로드일 때 원본 파일. 실패한 항목을 같은 줄에서 다시 올리는 데 씁니다. */
  file?: File;
  /** 큐에서 바로 "다시 시도"할 수 있는 항목인지. 녹음 중 만든 초안처럼 화면이 직접 다시 올리는 항목은 false입니다. */
  canRetry: boolean;
};

type Outcome = "uploaded" | "failed" | "cancelled";

function recordingName(): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `회의 녹음 ${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

/** 사용자가 취소한 업로드인지. apiUpload는 취소되면 "AbortError"로 거절합니다. */
export function isUploadCancelled(error: unknown): boolean {
  return typeof error === "object" && error !== null && "name" in error && error.name === "AbortError";
}

/**
 * 소스 업로드 큐를 관리합니다.
 *
 * 문서와 회의 녹음이 같은 큐를 쓰므로 진행률 표시와 처리 단계 이벤트를
 * 한 곳에서 이어받습니다. 전송이 끝나면 서버가 준 job이 항목에 붙습니다.
 *
 * 항목마다 AbortController를 두어 전송 중에도 취소할 수 있습니다. 이 훅을 쓰는
 * 화면이 닫혀도 진행 중인 전송은 끊지 않습니다(서버에는 끝까지 올라갑니다).
 */
export function useSourceUpload(workspaceId: string, onUploaded?: () => void) {
  const api = useApi();
  const [items, setItems] = useState<UploadItem[]>([]);
  const sequence = useRef(0);
  /** 전송 중인 항목의 취소 핸들 */
  const controllers = useRef(new Map<string, AbortController>());
  /** 큐에서 다시 시도할 때 실행할 작업 */
  const retries = useRef(new Map<string, () => Promise<Outcome>>());
  /** 같은 녹음을 다시 올리면 새 줄을 만들지 않고 기존 줄을 갱신합니다. */
  const recordingItems = useRef(new Map<Blob, string>());
  const failedTranscriptItem = useRef<string | undefined>(undefined);

  const patch = useCallback((id: string, changes: Partial<UploadItem>) => {
    setItems((current) => current.map((item) => (item.id === id ? { ...item, ...changes } : item)));
  }, []);

  const enqueue = useCallback(
    (fileName: string, sizeBytes: number, extra: Partial<UploadItem> = {}): UploadItem => {
      const item: UploadItem = {
        id: `upload-${++sequence.current}`,
        fileName,
        sizeBytes,
        status: "uploading",
        progress: 0,
        canRetry: false,
        ...extra,
      };
      setItems((current) => [item, ...current]);
      return item;
    },
    [],
  );

  const announceUploaded = useCallback(() => {
    onUploaded?.();
    window.dispatchEvent(new Event("maeglagi:sources-changed"));
  }, [onUploaded]);

  /** 한 항목의 전송을 실행합니다. 성공·실패·취소를 항목에 반영하고 결과만 돌려줍니다. */
  const transfer = useCallback(
    async (
      id: string,
      send: (options: { signal: AbortSignal; onProgress: (ratio: number) => void }) => Promise<ProcessingJob>,
    ): Promise<{ outcome: Outcome; error?: unknown }> => {
      const controller = new AbortController();
      controllers.current.set(id, controller);
      patch(id, { status: "uploading", progress: 0, errorMessage: undefined });
      try {
        const job = await send({
          signal: controller.signal,
          onProgress: (ratio) => {
            if (controllers.current.get(id) === controller) patch(id, { progress: ratio });
          },
        });
        patch(id, { status: "uploaded", progress: 1, job });
        return { outcome: "uploaded" };
      } catch (error) {
        if (controller.signal.aborted || isUploadCancelled(error)) {
          patch(id, { status: "cancelled", errorMessage: undefined });
          return { outcome: "cancelled", error };
        }
        // 전송이 멈춰 클라이언트 타임아웃으로 끝난 경우도 여기로 와서 다시 시도할 수 있는 실패 항목이 됩니다.
        patch(id, { status: "failed", errorMessage: toUserMessage(error, UPLOAD_FAILED) });
        return { outcome: "failed", error };
      } finally {
        if (controllers.current.get(id) === controller) controllers.current.delete(id);
      }
    },
    [patch],
  );

  const uploadDocuments = useCallback(
    async (files: File[]) => {
      const { accepted, rejected } = validateDocuments(files);

      for (const { file, reason } of rejected) {
        toast.error(`${file.name}: ${reason}`);
      }
      if (accepted.length === 0) return;

      const runs = accepted.map((file) => {
        const item = enqueue(file.name, file.size, { file, canRetry: true });
        const run = async () =>
          (await transfer(item.id, (options) => api.uploadDocument(workspaceId, file, options))).outcome;
        retries.current.set(item.id, async () => {
          const outcome = await run();
          if (outcome === "uploaded") {
            toast.success(`"${file.name}" 파일을 올렸습니다. 분석을 시작합니다.`);
            announceUploaded();
          } else if (outcome === "failed") toast.error(`"${file.name}" 파일을 올리지 못했습니다.`);
          return outcome;
        });
        return { file, run };
      });

      const outcomes = await Promise.all(runs.map(({ run }) => run()));
      const uploaded = outcomes.filter((outcome) => outcome === "uploaded").length;
      const failed = runs.filter((_, index) => outcomes[index] === "failed");

      // 실패 사유와 다시 시도는 큐 항목에 있으므로 토스트는 한 번만 띄웁니다.
      if (failed.length === 1) toast.error(`"${failed[0].file.name}" 파일을 올리지 못했습니다.`);
      else if (failed.length > 1) toast.error(`${failed.length}개 파일을 올리지 못했습니다.`);

      if (uploaded > 0) {
        toast.success(`${uploaded}개 파일을 올렸습니다. 분석을 시작합니다.`);
        announceUploaded();
      }
    },
    [workspaceId, enqueue, transfer, announceUploaded, api],
  );

  /**
   * 녹음이 끝나는 즉시 호출됩니다. 사용자가 따로 업로드를 누르지 않습니다.
   *
   * 실패하거나 취소되면 거절합니다(취소는 `isUploadCancelled`로 구분). `liveDraft`가 있는
   * 녹음은 호출한 화면이 편집 중인 대본과 함께 다시 올리므로 큐에서는 다시 시도를 제공하지 않습니다.
   */
  const uploadRecording = useCallback(
    async (audio: Blob, durationSeconds: number, liveDraft?: { utterances: MeetingUtterance[] }, projectId?: string, projectIds?: string[]) => {
      if (audio.size === 0) {
        toast.error("녹음된 내용이 없습니다.");
        throw new Error("녹음된 내용이 없습니다.");
      }

      const send = (draft: typeof liveDraft) => (options: { signal: AbortSignal; onProgress: (ratio: number) => void }) =>
        api.uploadRecording(workspaceId, audio, draft, projectId, { ...options, projectIds });
      const finish = (outcome: Outcome) => {
        if (outcome === "uploaded") {
          recordingItems.current.delete(audio);
          toast.success("녹음을 올렸습니다. 받아쓰기가 끝나면 대본을 검토해 주세요.");
          announceUploaded();
        } else if (outcome === "failed") toast.error(RECORDING_UPLOAD_FAILED);
      };

      const ownedByCaller = liveDraft !== undefined;
      let id = recordingItems.current.get(audio);
      if (id === undefined) {
        id = enqueue(
          typeof File !== "undefined" && audio instanceof File ? audio.name : recordingName(),
          audio.size,
          { durationSeconds: durationSeconds || undefined, canRetry: !ownedByCaller },
        ).id;
        recordingItems.current.set(audio, id);
      }
      const itemId = id;
      if (!ownedByCaller) {
        retries.current.set(itemId, async () => {
          const { outcome } = await transfer(itemId, send(undefined));
          finish(outcome);
          return outcome;
        });
      }

      const { outcome, error } = await transfer(itemId, send(liveDraft));
      finish(outcome);
      if (outcome !== "uploaded") throw error ?? new Error(UPLOAD_FAILED);
    },
    [workspaceId, enqueue, transfer, announceUploaded, api],
  );

  const uploadTranscript = useCallback(
    async (input: TranscriptSourceInput, projectId?: string) => {
      if (!input.text.trim()) return false;
      const sizeBytes = new Blob([input.text]).size;
      const fileName = input.title || "회의 대본";
      // 실패한 대본을 고쳐 다시 올리면 같은 줄을 갱신합니다.
      let id = failedTranscriptItem.current;
      failedTranscriptItem.current = undefined;
      if (id === undefined) id = enqueue(fileName, sizeBytes, { durationSeconds: input.durationSeconds }).id;
      else patch(id, { fileName, sizeBytes, durationSeconds: input.durationSeconds, status: "uploading", progress: 0, errorMessage: undefined });
      try {
        const job = await api.uploadTranscript(workspaceId, { ...input, projectId: projectId || null, projectIds: input.projectIds ?? (projectId ? [projectId] : []) });
        patch(id, { status: "uploaded", progress: 1, job });
        announceUploaded();
        toast.success("대본 초안을 올렸습니다. 검토한 뒤 확인해 주세요.");
        return true;
      } catch (error) {
        patch(id, {
          status: "failed",
          errorMessage: toUserMessage(error, UPLOAD_FAILED),
        });
        failedTranscriptItem.current = id;
        toast.error("대본을 올리지 못했습니다. 편집 내용은 유지됩니다.");
        return false;
      }
    },
    [workspaceId, enqueue, patch, announceUploaded, api],
  );

  /** 전송 중인 항목을 취소합니다. 항목은 "취소했습니다" 상태로 남고 오류 토스트는 띄우지 않습니다. */
  const cancel = useCallback((id: string) => {
    controllers.current.get(id)?.abort();
  }, []);

  /** 실패하거나 취소한 항목을 같은 줄에서 다시 올립니다. 이미 전송 중이면 무시합니다. */
  const retry = useCallback((id: string) => {
    if (controllers.current.has(id)) return;
    void retries.current.get(id)?.();
  }, []);

  const dismiss = useCallback((id: string) => {
    controllers.current.get(id)?.abort();
    retries.current.delete(id);
    for (const [audio, itemId] of recordingItems.current) if (itemId === id) recordingItems.current.delete(audio);
    if (failedTranscriptItem.current === id) failedTranscriptItem.current = undefined;
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  return { items, uploadDocuments, uploadRecording, uploadTranscript, cancel, retry, dismiss };
}
