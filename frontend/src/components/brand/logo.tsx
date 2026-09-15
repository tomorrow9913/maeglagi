import { cn } from "@/lib/utils";

/**
 * 맥락이 심볼.
 *
 * 아래로 흩어진 두 가닥이 위에서 하나의 고리로 감기는 실타래입니다.
 * 제품이 하는 일(흩어진 정보를 하나의 맥락으로 잇는다)을 그대로 형태로 옮겼습니다.
 *
 * 색은 `currentColor`를 따릅니다. 배경이 무엇이든 부모의 text 색만 맞추면 되고,
 * 브랜드 색으로 쓸 때는 `text-primary`를 줍니다.
 */
export function MaeglagiMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      className={cn("size-6", className)}
      fill="none"
      stroke="currentColor"
      strokeWidth="2.6"
      strokeLinecap="round"
      aria-hidden
    >
      <circle cx="16" cy="13.5" r="8.5" />
      <path d="M11.8 20.9C13.6 24.4 19 25.4 22.4 28.8" />
      <path d="M20.2 20.9C18.4 24.4 13 25.4 9.6 28.8" />
    </svg>
  );
}

/**
 * 워드마크 — 심볼과 서비스명을 묶은 기본 락업입니다.
 *
 * 서비스명은 항상 `맥락이` 한 단어로만 씁니다. 부제나 영문 병기를 붙이지 않습니다.
 * 크기는 부모의 폰트 크기를 따라가므로 헤더·푸터에서 `text-sm`, `text-lg`처럼
 * Tailwind 스케일로만 조절합니다.
 */
export function MaeglagiWordmark({ className }: { className?: string }) {
  return (
    <span
      className={cn("inline-flex items-center gap-1.5 font-semibold tracking-tight", className)}
    >
      {/* 심볼은 글자 크기를 따라가야 락업 비율이 유지되므로 em 단위로 묶어둡니다. */}
      <MaeglagiMark className="size-[1.15em] text-primary" />
      맥락이
    </span>
  );
}
