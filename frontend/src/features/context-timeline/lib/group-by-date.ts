import type { ContextItem } from "@/lib/api";

export type TimelineGroup = {
  /** YYYY-MM-DD */
  date: string;
  label: string;
  items: ContextItem[];
};

const weekdays = ["일", "월", "화", "수", "목", "금", "토"];

function labelFor(date: string): string {
  const [year, month, day] = date.split("-").map(Number);
  const weekday = weekdays[new Date(Date.UTC(year, month - 1, day)).getUTCDay()];
  return `${year}년 ${month}월 ${day}일 (${weekday})`;
}

/**
 * 맥락 항목을 날짜별로 묶습니다.
 *
 * 최신 날짜가 위로 오고, 그룹 안에서도 최신 항목이 먼저입니다.
 */
export function groupByDate(items: ContextItem[]): TimelineGroup[] {
  const buckets = new Map<string, ContextItem[]>();

  for (const item of items) {
    const date = item.occurredAt.slice(0, 10);
    const bucket = buckets.get(date);
    if (bucket) bucket.push(item);
    else buckets.set(date, [item]);
  }

  return [...buckets.entries()]
    .sort(([a], [b]) => b.localeCompare(a))
    .map(([date, groupItems]) => ({
      date,
      label: labelFor(date),
      items: [...groupItems].sort((a, b) => b.occurredAt.localeCompare(a.occurredAt)),
    }));
}
