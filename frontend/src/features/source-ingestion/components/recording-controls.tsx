"use client";

import { Mic, Square } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type RecordingState = "idle" | "recording" | "uploading";

export type RecordingControlsProps = {
  state: RecordingState;
  /** 녹음 경과 시간(초). 표시용으로만 씁니다. */
  elapsedSeconds?: number;
  onStart: () => void;
  onStop: () => void;
};

function formatElapsed(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

/**
 * 회의 녹음 시작/정지 컨트롤입니다.
 *
 * MediaRecorder 연결과 업로드는 Day 2 회의 녹음 작업에서 붙입니다.
 * 여기서는 상태를 받아 표시만 하고, 실제 제어는 상위에서 넘깁니다.
 */
export function RecordingControls({
  state,
  elapsedSeconds = 0,
  onStart,
  onStop,
}: RecordingControlsProps) {
  const isRecording = state === "recording";

  return (
    <div className="flex items-center gap-4 rounded-xl border border-border bg-card p-4">
      <span
        aria-hidden
        className={cn(
          "size-2.5 rounded-full",
          isRecording ? "animate-pulse bg-destructive" : "bg-muted-foreground/40",
        )}
      />
      <div className="flex-1">
        <p className="text-sm font-medium">
          {isRecording ? "녹음 중" : state === "uploading" ? "업로드 중" : "녹음 준비됨"}
        </p>
        <p className="font-mono text-xs text-muted-foreground tabular-nums">
          {formatElapsed(elapsedSeconds)}
        </p>
      </div>
      {isRecording ? (
        <Button type="button" variant="destructive" size="sm" onClick={onStop}>
          <Square className="size-4" aria-hidden />
          정지
        </Button>
      ) : (
        <Button type="button" size="sm" disabled={state === "uploading"} onClick={onStart}>
          <Mic className="size-4" aria-hidden />
          녹음 시작
        </Button>
      )}
    </div>
  );
}
