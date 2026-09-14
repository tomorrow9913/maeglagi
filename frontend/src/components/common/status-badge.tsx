import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger";

/**
 * shadcn `Badge`의 래퍼입니다.
 *
 * `components/ui/badge.tsx` 원본은 건드리지 않고, 프로젝트에서 필요한
 * 상태 색(성공/경고/정보)만 여기서 얹습니다.
 */
const toneClass: Record<StatusTone, string> = {
  neutral: "bg-muted text-muted-foreground border-transparent",
  info: "bg-info/12 text-info border-info/25",
  success: "bg-success/12 text-success border-success/25",
  warning: "bg-warning/15 text-warning border-warning/30",
  danger: "bg-destructive/12 text-destructive border-destructive/25",
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
  return (
    <Badge variant="outline" className={cn(toneClass[tone], className)}>
      {children}
    </Badge>
  );
}
