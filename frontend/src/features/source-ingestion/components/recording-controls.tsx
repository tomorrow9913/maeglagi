"use client";

import { AlertCircle, Mic, Square } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { RecorderStatus } from "../hooks/use-audio-recorder";

export type RecordingControlsProps = {
  status: RecorderStatus;
  /** 녹음 경과 시간(초) */
  elapsedSeconds: number;
  errorMessage?: string;
  onStart: () => void;
  onStop: () => void;
  disableStart?: boolean;
  /** 끝난 녹음을 올리는 중인지. 상태 문구를 "녹음 준비됨" 대신 업로드 중으로 보여줍니다. */
  isUploading?: boolean;
};

function formatElapsed(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

const statusLabel: Record<RecorderStatus, string> = {
  idle: "녹음 준비됨",
  requesting: "마이크 권한 요청 중",
  recording: "녹음 중",
  stopping: "녹음 마무리 중",
  denied: "마이크 권한 필요",
  unsupported: "녹음을 지원하지 않는 브라우저",
  error: "녹음 실패",
};

/**
 * 회의 녹음 시작/정지 컨트롤입니다.
 *
 * 녹음이 끝나면 업로드는 자동으로 이어지므로 별도 업로드 버튼이 없습니다.
 */
export function RecordingControls({
  status,
  elapsedSeconds,
  errorMessage,
  onStart,
  onStop,
  disableStart = false,
  isUploading = false,
}: RecordingControlsProps) {
  const isRecording = status === "recording";
  const isBusy = status === "requesting" || status === "stopping";
  const hasFailed = status === "denied" || status === "unsupported" || status === "error";

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center gap-4">
        <span
          aria-hidden
          className={cn(
            "size-2.5 shrink-0 rounded-full",
            isRecording && "animate-pulse bg-destructive",
            !isRecording && hasFailed && "bg-destructive/50",
            !isRecording && !hasFailed && "bg-muted-foreground/40",
          )}
        />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{status === "idle" && isUploading ? "녹음을 올리는 중" : statusLabel[status]}</p>
          <p
            className="font-mono text-xs text-muted-foreground tabular-nums"
            aria-live={isRecording ? "off" : "polite"}
          >
            {formatElapsed(elapsedSeconds)}
          </p>
        </div>

        {isRecording ? (
          <Button type="button" variant="destructive" size="sm" onClick={onStop}>
            <Square className="size-4" aria-hidden />
            정지
          </Button>
        ) : (
          <Button
            type="button"
            size="sm"
            disabled={isBusy || disableStart || status === "unsupported"}
            onClick={onStart}
          >
            <Mic className="size-4" aria-hidden />
            {status === "denied" || status === "error" ? "다시 시도" : "녹음 시작"}
          </Button>
        )}
      </div>

      {hasFailed && errorMessage ? (
        <p className="mt-3 flex items-start gap-2 text-xs text-destructive" role="alert">
          <AlertCircle className="mt-px size-3.5 shrink-0" aria-hidden />
          {errorMessage}
        </p>
      ) : null}
    </div>
  );
}
