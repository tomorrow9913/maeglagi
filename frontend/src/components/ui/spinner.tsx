import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * 진행 중 표시. 크기는 주변 글자 크기를 따르도록 기본을 `size-4`로 둡니다.
 *
 * 옆에 진행 문구가 있으면 장식이므로 `label`을 비우고, 스피너만 단독으로 쓸 때는
 * 스크린리더가 읽을 `label`을 넘깁니다.
 */
export function Spinner({ className, label }: { className?: string; label?: string }) {
  return (
    <>
      <Loader2 className={cn("size-4 shrink-0 animate-spin", className)} aria-hidden />
      {label ? <span className="sr-only">{label}</span> : null}
    </>
  );
}
