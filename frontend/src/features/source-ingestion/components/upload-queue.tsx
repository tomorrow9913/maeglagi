"use client";

import { AlertCircle, CheckCircle2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import type { ProcessingJob } from "@/lib/api";
import { cn } from "@/lib/utils";

import type { UploadItem } from "../hooks/use-source-upload";
import { formatBytes, formatDuration } from "../lib/format";
import { ProcessingTracker } from "./processing-tracker";

/**
 * 업로드 중인 파일들의 상태를 한 줄씩 보여줍니다.
 *
 * 전송 중에는 전송 진행률을, 전송이 끝난 뒤에는 폴링으로 받은 처리 단계를
 * 이어서 표시합니다.
 */
export function UploadQueue({
  items,
  jobs,
  onDismiss,
  className,
}: {
  items: UploadItem[];
  /** jobId → 폴링으로 갱신되는 최신 처리 상태 */
  jobs: Record<string, ProcessingJob>;
  onDismiss: (id: string) => void;
  className?: string;
}) {
  if (items.length === 0) return null;

  return (
    <ul className={cn("space-y-2", className)} aria-label="업로드 진행 상황">
      {items.map((item) => {
        // 폴링 결과가 아직 없으면 업로드 응답으로 받은 초기 job을 씁니다.
        const job = item.job ? (jobs[item.job.id] ?? item.job) : undefined;
        const hasFailed = item.status === "failed" || job?.status === "failed";
        const hasSucceeded = job?.status === "succeeded";

        return (
          <li key={item.id} className="rounded-xl border border-border bg-card p-3">
            <div className="flex items-center gap-2">
              {hasFailed ? (
                <AlertCircle className="size-4 shrink-0 text-destructive" aria-hidden />
              ) : hasSucceeded ? (
                <CheckCircle2 className="size-4 shrink-0 text-success" aria-hidden />
              ) : null}
              <span className="truncate text-sm font-medium">{item.fileName}</span>
              <span className="ml-auto shrink-0 text-xs text-muted-foreground tabular-nums">
                {item.status === "uploading"
                  ? `${Math.round(item.progress * 100)}%`
                  : item.durationSeconds !== undefined
                    ? formatDuration(item.durationSeconds)
                    : formatBytes(item.sizeBytes)}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-6 shrink-0"
                aria-label={`${item.fileName} 목록에서 지우기`}
                onClick={() => onDismiss(item.id)}
              >
                <X className="size-3.5" aria-hidden />
              </Button>
            </div>

            {item.status === "uploading" ? (
              <Progress value={item.progress * 100} className="mt-2 h-1" />
            ) : item.status === "failed" ? (
              <p className="mt-1.5 text-xs text-destructive">{item.errorMessage}</p>
            ) : job ? (
              <ProcessingTracker job={job} className="mt-2" />
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
