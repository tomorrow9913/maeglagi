"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";

/**
 * 렌더 중 예외를 잡아 흰 화면 대신 복구 수단을 보여줍니다.
 *
 * 데모 중에는 새로고침보다 재시도가 빠르므로 reset을 먼저 제시합니다.
 */
export default function ErrorBoundary({
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
    <main className="mx-auto flex min-h-dvh w-full max-w-lg flex-col items-center justify-center gap-4 px-5 text-center">
      <h1 className="text-lg font-semibold">문제가 생겼습니다</h1>
      <p className="text-sm text-muted-foreground">
        화면을 그리는 중 오류가 났습니다. 다시 시도해도 같으면 새로고침해 주세요.
      </p>
      {error.digest ? (
        <p className="font-mono text-xs text-muted-foreground">오류 코드: {error.digest}</p>
      ) : null}
      <div className="flex gap-2">
        <Button onClick={reset}>다시 시도</Button>
        <Button variant="outline" onClick={() => window.location.reload()}>
          새로고침
        </Button>
      </div>
    </main>
  );
}
