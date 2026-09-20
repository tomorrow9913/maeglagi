import type { ContextItem } from "@/lib/api";
import { localDateKey, localDateLabel } from "@/lib/format-date";

export type TimelineGroup = {
  /** 보는 사람의 현지 날짜 YYYY-MM-DD */
  date: string;
  label: string;
  items: ContextItem[];
};

/** 시각 표기(Z, +09:00)가 섞여 있어도 순서가 맞도록 문자열이 아니라 시각으로 비교합니다. */
function timeOf(iso: string): number {
  const time = Date.parse(iso);
  return Number.isNaN(time) ? 0 : time;
}

/**
 * 맥락 항목을 날짜별로 묶습니다.
 *
 * 최신 날짜가 위로 오고, 그룹 안에서도 최신 항목이 먼저입니다.
 *
 * `occurredAt`은 UTC라서 문자열 앞 10자리로 묶으면 자정 전후 항목이 하루 어긋납니다.
 * 보는 사람의 현지 날짜로 묶고, `timeZone`은 테스트에서 값을 고정할 때만 넘깁니다.
 */
export function groupByDate(items: ContextItem[], timeZone?: string): TimelineGroup[] {
  const buckets = new Map<string, ContextItem[]>();

  for (const item of items) {
    const date = localDateKey(item.occurredAt, timeZone);
    const bucket = buckets.get(date);
    if (bucket) bucket.push(item);
    else buckets.set(date, [item]);
  }

  return [...buckets.entries()]
    .sort(([a], [b]) => b.localeCompare(a))
    .map(([date, groupItems]) => {
      // 같은 그룹이면 어느 항목으로 만들어도 라벨이 같습니다.
      const sorted = [...groupItems].sort((a, b) => timeOf(b.occurredAt) - timeOf(a.occurredAt));
      return { date, label: localDateLabel(sorted[0].occurredAt, timeZone), items: sorted };
    });
}
