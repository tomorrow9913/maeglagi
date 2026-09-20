"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";

/**
 * 워크스페이스 안쪽 화면에서 렌더 예외가 났을 때 본문 자리만 바꿉니다.
 *
 * 루트 `app/error.tsx`는 헤더와 내비게이션까지 대체해 다른 메뉴로 빠져나갈 수 없습니다.
 * 세그먼트에 이 화면을 두면 셸이 남아 있어 다른 화면으로 옮겨 갈 수 있습니다.
 */
export function SegmentError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-3 rounded-xl border border-border bg-card p-10 text-center"
    >
      <h2 className="text-sm font-medium">이 화면을 그리지 못했습니다</h2>
      <p className="text-sm text-muted-foreground">
        다시 시도해도 같으면 새로고침하거나 왼쪽 메뉴에서 다른 화면으로 옮겨 주세요.
      </p>
      {error.digest ? (
        <p className="font-mono text-xs text-muted-foreground">오류 코드: {error.digest}</p>
      ) : null}
      <div className="flex gap-2">
        <Button size="sm" onClick={reset}>
          다시 시도
        </Button>
        <Button size="sm" variant="outline" onClick={() => window.location.reload()}>
          새로고침
        </Button>
      </div>
    </div>
  );
}
