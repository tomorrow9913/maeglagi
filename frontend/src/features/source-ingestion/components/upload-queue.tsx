"use client";

import { AlertCircle, CheckCircle2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

import type { UploadItem } from "../hooks/use-source-upload";
import type { LiveJob } from "../hooks/use-job-events";
import type { SourceEventsConnection } from "../hooks/use-workspace-source-events";
import { CONNECTION_DELAYED, UPLOAD_CANCELLED } from "../lib/copy";
import { formatBytes, formatDuration } from "../lib/format";
import { ProcessingTracker } from "./processing-tracker";

/**
 * 업로드 중인 파일들의 상태를 한 줄씩 보여줍니다.
 *
 * 전송 중에는 전송 진행률을, 전송이 끝난 뒤에는 이벤트로 받은 처리 단계를
 * 이어서 표시합니다.
 */
export function UploadQueue({
  items,
  jobs,
  connection = "connected",
  onDismiss,
  onCancel,
  onRetry,
  onReview,
  onRefresh,
  className,
}: {
  items: UploadItem[];
  /** jobId → 이벤트로 갱신되는 최신 처리 상태 */
  jobs: Record<string, LiveJob>;
  /** 처리 상태 스트림 연결 상태. 끊겨서 다시 연결하는 동안 안내를 보여줍니다. */
  connection?: SourceEventsConnection;
  onDismiss: (id: string) => void;
  /** 전송 중인 항목을 취소합니다. */
  onCancel: (id: string) => void;
  /** 실패하거나 취소한 항목을 같은 줄에서 다시 올립니다. */
  onRetry: (id: string) => void;
  onReview?: (sourceId: string) => void;
  /** 처리 상태를 확인하지 못했을 때 목록을 다시 불러옵니다. */
  onRefresh?: () => void;
  className?: string;
}) {
  if (items.length === 0) return null;

  const waitingForEvents = items.some((item) => {
    const job = item.job ? (jobs[item.job.id] ?? item.job) : undefined;
    return job && (job.status === "queued" || job.status === "enqueue_pending" || job.status === "processing");
  });

  return (
    <div className={cn("space-y-2", className)}>
      {connection === "reconnecting" && waitingForEvents ? (
        <p role="status" className="text-xs text-muted-foreground">{CONNECTION_DELAYED}</p>
      ) : null}
      <ul className="space-y-2" aria-label="업로드 진행 상황">
        {items.map((item) => {
          // 이벤트가 아직 없으면 업로드 응답으로 받은 초기 job을 씁니다.
          const job = item.job ? (jobs[item.job.id] ?? item.job) : undefined;
          const isUploading = item.status === "uploading";
          const hasFailed = item.status === "failed" || job?.status === "failed";
          const hasSucceeded = job?.status === "succeeded";
          // 전송은 끝났지만 서버가 파일을 확인하고 응답하기 전입니다.
          const isVerifying = isUploading && item.progress >= 1;

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
                  {isVerifying
                    ? "서버에서 확인하는 중"
                    : isUploading
                      ? `${Math.round(item.progress * 100)}%`
                      : item.durationSeconds !== undefined
                        ? formatDuration(item.durationSeconds)
                        : formatBytes(item.sizeBytes)}
                </span>
                {isUploading ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-6 shrink-0"
                    aria-label={`${item.fileName} 업로드 취소`}
                    title="업로드 취소"
                    onClick={() => onCancel(item.id)}
                  >
                    <X className="size-3.5" aria-hidden />
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-6 shrink-0"
                    aria-label={`${item.fileName} 목록에서 지우기`}
                    title="목록에서 지우기"
                    onClick={() => onDismiss(item.id)}
                  >
                    <X className="size-3.5" aria-hidden />
                  </Button>
                )}
              </div>

              {isUploading ? (
                <Progress
                  value={item.progress * 100}
                  className="mt-2 h-1"
                  aria-label={`${item.fileName} 업로드 진행률`}
                  aria-valuenow={Math.round(item.progress * 100)}
                />
              ) : item.status === "failed" || item.status === "cancelled" ? (
                <div className="mt-1.5 flex flex-wrap items-center gap-2">
                  {item.status === "failed" ? (
                    <p role="alert" className="text-xs text-destructive">{item.errorMessage}</p>
                  ) : (
                    <p role="status" className="text-xs text-muted-foreground">{UPLOAD_CANCELLED}</p>
                  )}
                  {item.canRetry ? (
                    <Button
                      type="button"
                      size="xs"
                      variant="outline"
                      aria-label={`${item.fileName} 업로드 다시 시도`}
                      onClick={() => onRetry(item.id)}
                    >
                      다시 시도
                    </Button>
                  ) : null}
                </div>
              ) : job?.eventError ? (
                <div role="alert" className="mt-2 flex flex-wrap items-center gap-2 text-xs text-destructive">
                  <span>{job.eventError}</span>
                  {onRefresh ? (
                    <Button type="button" size="xs" variant="outline" onClick={onRefresh}>
                      소스 목록 새로고침
                    </Button>
                  ) : null}
                </div>
              ) : job ? (
                <>
                  <ProcessingTracker job={job} label={item.fileName} className="mt-2" />
                  {(job.status === "awaiting_review" || (job.status === "failed" && job.sourceKind === "meeting")) && onReview ? (
                    <Button size="sm" className="mt-2" onClick={() => onReview(job.sourceId)}>
                      {job.status === "failed" ? "대본·재시도 열기" : "대본 검토"}
                    </Button>
                  ) : null}
                </>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
