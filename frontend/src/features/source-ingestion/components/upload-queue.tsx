"use client";

import { AlertCircle, CheckCircle2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

import { formatBytes } from "../lib/validate-file";
import type { UploadItem } from "../hooks/use-document-upload";

/** 업로드 중인 파일들의 전송 진행률을 한 줄씩 보여줍니다. */
export function UploadQueue({
  items,
  onDismiss,
  className,
}: {
  items: UploadItem[];
  onDismiss: (id: string) => void;
  className?: string;
}) {
  if (items.length === 0) return null;

  return (
    <ul className={cn("space-y-2", className)} aria-label="업로드 진행 상황">
      {items.map((item) => (
        <li key={item.id} className="rounded-xl border border-border bg-card p-3">
          <div className="flex items-center gap-2">
            {item.status === "uploaded" ? (
              <CheckCircle2 className="size-4 shrink-0 text-success" aria-hidden />
            ) : item.status === "failed" ? (
              <AlertCircle className="size-4 shrink-0 text-destructive" aria-hidden />
            ) : null}
            <span className="truncate text-sm font-medium">{item.fileName}</span>
            <span className="ml-auto shrink-0 text-xs text-muted-foreground tabular-nums">
              {item.status === "uploading"
                ? `${Math.round(item.progress * 100)}%`
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
          ) : (
            <p className="mt-1.5 text-xs text-muted-foreground">업로드 완료 · 분석 대기 중</p>
          )}
        </li>
      ))}
    </ul>
  );
}
