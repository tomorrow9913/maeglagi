import type { StatusTone } from "@/components/common/status-badge";
import type { ContextKind } from "@/types/context";

/** 카드 배지와 타임라인 점이 같은 색 규칙을 쓰도록 한 곳에 둡니다. */
export const kindTone: Record<ContextKind, StatusTone> = {
  decision: "success",
  issue: "danger",
  task: "info",
  event: "neutral",
};

export const kindDotClass: Record<ContextKind, string> = {
  decision: "bg-success",
  issue: "bg-destructive",
  task: "bg-info",
  event: "bg-muted-foreground",
};
