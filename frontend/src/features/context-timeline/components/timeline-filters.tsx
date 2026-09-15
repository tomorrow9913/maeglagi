"use client";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { contextKindLabel, type ContextKind, type SourceKind } from "@/types/context";

const contextKinds: ContextKind[] = ["decision", "issue", "task", "event"];
const sourceKinds: { value: SourceKind; label: string }[] = [
  { value: "meeting", label: "회의" },
  { value: "document", label: "문서" },
];

export type TimelineFilterState = {
  kinds: ContextKind[];
  sourceKinds: SourceKind[];
};

function Chip({
  isActive,
  onClick,
  children,
}: {
  isActive: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={isActive}
      onClick={onClick}
      className={cn(
        "rounded-full border px-3 py-1 text-xs transition-colors",
        isActive
          ? "border-primary bg-primary text-primary-foreground"
          : "border-border text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

/**
 * Timeline 필터입니다.
 *
 * 아무것도 고르지 않은 상태가 "전체"입니다. 선택을 비우는 쪽이 전체를 다시
 * 보는 가장 빠른 길이라 별도 전체 버튼 대신 토글로 둡니다.
 */
export function TimelineFilters({
  value,
  onChange,
}: {
  value: TimelineFilterState;
  onChange: (next: TimelineFilterState) => void;
}) {
  const toggle = <T,>(list: T[], item: T): T[] =>
    list.includes(item) ? list.filter((entry) => entry !== item) : [...list, item];

  const hasFilter = value.kinds.length > 0 || value.sourceKinds.length > 0;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs text-muted-foreground">종류</span>
        {contextKinds.map((kind) => (
          <Chip
            key={kind}
            isActive={value.kinds.includes(kind)}
            onClick={() => onChange({ ...value, kinds: toggle(value.kinds, kind) })}
          >
            {contextKindLabel[kind]}
          </Chip>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs text-muted-foreground">소스</span>
        {sourceKinds.map(({ value: kind, label }) => (
          <Chip
            key={kind}
            isActive={value.sourceKinds.includes(kind)}
            onClick={() => onChange({ ...value, sourceKinds: toggle(value.sourceKinds, kind) })}
          >
            {label}
          </Chip>
        ))}
      </div>

      {hasFilter ? (
        <Button
          variant="ghost"
          size="sm"
          className="h-7 text-xs"
          onClick={() => onChange({ kinds: [], sourceKinds: [] })}
        >
          필터 해제
        </Button>
      ) : null}
    </div>
  );
}
