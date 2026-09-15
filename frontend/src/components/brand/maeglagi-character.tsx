import { cn } from "@/lib/utils";

/**
 * 맥락이 캐릭터.
 *
 * 실타래 몸통에서 실 한 가닥이 풀려 나오는 모습입니다. 심볼과 같은 은유를 쓰되,
 * 심볼은 마크로, 캐릭터는 말을 거는 화자로 역할을 나눕니다.
 *
 * 포즈는 두 가지만 씁니다.
 * - `default` : 사용자를 보고 있는 기본 포즈. 답변 화자 아바타에 씁니다.
 * - `resting` : 눈을 감고 실이 길게 풀린 포즈. 로딩과 빈 상태에만 씁니다.
 *
 * 색은 `currentColor`를 따르므로 부모에서 `text-primary`로 지정합니다.
 */
export function MaeglagiCharacter({
  variant = "default",
  className,
}: {
  variant?: "default" | "resting";
  className?: string;
}) {
  const isResting = variant === "resting";

  return (
    <svg viewBox="0 0 32 32" className={cn("size-8", className)} fill="none" aria-hidden>
      {/* 몸통 — 감긴 실타래 */}
      <circle cx="16" cy="15" r="9.5" fill="currentColor" fillOpacity="0.16" />
      <circle cx="16" cy="15" r="9.5" stroke="currentColor" strokeWidth="1.8" />

      {/* 감긴 결. 얼굴을 피해 위아래 가장자리에만 둡니다. */}
      <g stroke="currentColor" strokeWidth="1.2" strokeOpacity="0.45" strokeLinecap="round">
        <path d="M9.4 9.4C12.5 7.6 19.5 7.6 22.6 9.4" />
        <path d="M10 22C12.4 23.4 19.6 23.4 22 22" />
      </g>

      {/* 얼굴 */}
      {isResting ? (
        <g stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
          <path d="M11.5 14.4C12.2 13.3 13.4 13.3 14.1 14.4" />
          <path d="M17.9 14.4C18.6 13.3 19.8 13.3 20.5 14.4" />
        </g>
      ) : (
        <g fill="currentColor">
          <circle cx="12.8" cy="14" r="1.3" />
          <circle cx="19.2" cy="14" r="1.3" />
        </g>
      )}
      <path
        d={
          isResting
            ? "M14.6 17.8C15.2 18.3 16.8 18.3 17.4 17.8"
            : "M14.2 17.6C15 18.7 17 18.7 17.8 17.6"
        }
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />

      {/* 풀려 나온 실 한 가닥. 쉬는 포즈에서는 더 길게 늘어집니다. */}
      <path
        d={
          isResting
            ? "M7.1 18.3C3.6 20.2 5.6 24.4 2.2 26.4"
            : "M7.1 18.3C4.6 19.9 5.6 23.2 3.4 24.8"
        }
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}
