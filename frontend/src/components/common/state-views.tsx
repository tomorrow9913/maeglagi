import type { ReactNode } from "react";
import Link from "next/link";
import { AlertCircle } from "lucide-react";

import { MaeglagiCharacter } from "@/components/brand/maeglagi-character";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/client";
import { toUserMessage } from "@/lib/api/error-message";
import { cn } from "@/lib/utils";

import { SlowNotice } from "./slow-notice";

/**
 * 빈 상태·에러·로딩을 한 곳에 모아 화면마다 다르게 보이지 않게 합니다.
 *
 * 세 상태 모두 "지금 무슨 일이 일어났는지"와 "다음에 뭘 하면 되는지"를
 * 함께 보여주는 것을 규칙으로 삼습니다.
 */

export function EmptyState({
  title,
  description,
  action,
  icon,
  className,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-3 rounded-xl border border-dashed border-border p-10 text-center",
        className,
      )}
    >
      <span className="text-muted-foreground" aria-hidden>
        {icon ?? <MaeglagiCharacter variant="resting" className="size-9 text-primary" />}
      </span>
      <div className="space-y-1">
        <p className="text-sm font-medium">{title}</p>
        {description ? <p className="text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  title = "불러오지 못했습니다",
  compact = false,
  className,
}: {
  error: Error;
  onRetry?: () => void;
  title?: string;
  /** 사이드바·다이얼로그처럼 좁은 자리에 넣을 때 */
  compact?: boolean;
  className?: string;
}) {
  // 세션 만료는 다시 시도해도 풀리지 않으므로 로그인으로 안내합니다.
  const needsLogin = error instanceof ApiError && error.kind === "auth";

  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center gap-3 rounded-xl border border-border bg-card text-center",
        compact ? "p-4" : "p-10",
        className,
      )}
    >
      <AlertCircle className="size-5 text-destructive" aria-hidden />
      <div className="space-y-1">
        <p className="text-sm font-medium">{title}</p>
        <p className="text-sm text-muted-foreground">
          {toUserMessage(error, "잠시 후 다시 시도해 주세요.")}
        </p>
      </div>
      {needsLogin ? (
        <Button variant="outline" size="sm" asChild>
          <Link href="/login">다시 로그인</Link>
        </Button>
      ) : onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          다시 시도
        </Button>
      ) : null}
    </div>
  );
}

/** 목록 자리를 채우는 스켈레톤. 화면마다 높이와 개수만 다릅니다. */
export function ListSkeleton({
  count = 3,
  className = "h-24",
  label = "불러오는 중",
}: {
  count?: number;
  className?: string;
  /** 스크린리더에 읽어 줄 진행 문구 */
  label?: string;
}) {
  return (
    <div role="status" className="space-y-3">
      <span className="sr-only">{label}</span>
      <div className="space-y-3" aria-hidden>
        {Array.from({ length: count }, (_, index) => (
          <Skeleton key={index} className={cn("w-full rounded-xl", className)} />
        ))}
      </div>
      <SlowNotice />
    </div>
  );
}
