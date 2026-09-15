import { MaeglagiCharacter } from "@/components/brand/maeglagi-character";
import { cn } from "@/lib/utils";

/**
 * 답변의 화자 아바타입니다.
 *
 * 브랜드 캐릭터를 그대로 쓰되, 이 화면에서 필요한 크기와 정렬만 여기서 정합니다.
 */
export function MaeglagiAvatar({
  variant = "default",
  className,
}: {
  variant?: "default" | "resting";
  className?: string;
}) {
  return (
    <MaeglagiCharacter
      variant={variant}
      className={cn("size-8 shrink-0 text-primary", className)}
    />
  );
}
