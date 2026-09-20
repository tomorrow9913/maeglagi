"use client";

import { useEffect, useState } from "react";

/** 이 시간이 지나도 로딩이 끝나지 않으면 이유를 알려줍니다. */
const SLOW_AFTER_MS = 8_000;

/**
 * 로딩이 길어질 때만 나타나는 안내.
 *
 * 오래 쉬던 서버는 첫 요청에 수십 초가 걸립니다. 그동안 스켈레톤만 보이면 멈춘 것처럼
 * 느껴지므로, 기다리는 이유를 적습니다. 시간은 약속하지 않습니다(docs/voice.md 4절).
 */
export function SlowNotice({ className }: { className?: string }) {
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setSlow(true), SLOW_AFTER_MS);
    return () => clearTimeout(timer);
  }, []);

  if (!slow) return null;
  return (
    <p className={className ?? "text-center text-sm text-muted-foreground"}>
      응답이 평소보다 늦어지고 있어요. 오래 쉬던 서버는 첫 요청에 시간이 걸려요.
    </p>
  );
}
