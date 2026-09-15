import { cn } from "@/lib/utils";

/**
 * 맥락이 캐릭터 자리표시자입니다.
 *
 * 디자인에서 정식 캐릭터가 나오면 이 컴포넌트의 내용만 교체하면 됩니다.
 * 흩어진 점을 선으로 잇는 모양으로 제품의 은유를 담았습니다.
 */
export function MaeglagiAvatar({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10",
        className,
      )}
      aria-hidden
    >
      <svg viewBox="0 0 24 24" className="size-5 text-primary" fill="none">
        <path
          d="M5 16.5 10 9l4.5 5L19 6.5"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="5" cy="16.5" r="2" fill="currentColor" />
        <circle cx="10" cy="9" r="2" fill="currentColor" />
        <circle cx="14.5" cy="14" r="2" fill="currentColor" />
        <circle cx="19" cy="6.5" r="2" fill="currentColor" />
      </svg>
    </span>
  );
}
