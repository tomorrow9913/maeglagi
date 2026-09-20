import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger";

/**
 * shadcn `Badge`의 래퍼입니다.
 *
 * `components/ui/badge.tsx` 원본은 건드리지 않고, 프로젝트에서 필요한
 * 상태 색(성공/경고/정보)만 여기서 얹습니다.
 *
 * 글자는 상태 색이 아니라 `text-foreground`로 씁니다. 옅은 상태 색 면 위에 같은
 * 상태 색 글자를 올리면 대비가 3.6~4.5:1에 그쳐 brand.md의 4.5:1 기준에 못 미칩니다
 * (warning이 가장 낮습니다). 본문색 글자는 어느 면 위에서도 10:1을 넘고, 색 단서는
 * 앞의 점과 테두리가 맡습니다. 점은 글자가 아닌 그래픽이라 3:1 기준을 적용합니다.
 */
const toneClass: Record<StatusTone, string> = {
  neutral: "bg-muted text-muted-foreground border-transparent",
  info: "bg-info/10 text-foreground border-info/30",
  success: "bg-success/10 text-foreground border-success/30",
  warning: "bg-warning/10 text-foreground border-warning/30",
  danger: "bg-destructive/10 text-foreground border-destructive/30",
};

const dotClass: Record<StatusTone, string | undefined> = {
  neutral: undefined,
  info: "bg-info",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-destructive",
};

export function StatusBadge({
  tone = "neutral",
  className,
  children,
}: {
  tone?: StatusTone;
  className?: string;
  children: React.ReactNode;
}) {
  const dot = dotClass[tone];

  return (
    <Badge variant="outline" className={cn(toneClass[tone], className)}>
      {dot ? <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", dot)} /> : null}
      {children}
    </Badge>
  );
}
