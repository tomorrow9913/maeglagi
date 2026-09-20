/**
 * 서버 시각(UTC ISO 문자열)을 보는 사람의 현지 시각으로 바꿔 보여줍니다.
 *
 * ISO 문자열을 그대로 잘라 쓰면 UTC 기준이라, 한국에서 15:20에 연 회의가 "06:20"으로
 * 보이고 자정 전후 항목은 날짜도 하루 어긋납니다. `timeZone`을 비우면 브라우저의
 * 시간대를 쓰고, 테스트에서는 값을 고정하려고 직접 넘깁니다.
 */

function parts(iso: string, timeZone?: string): Record<string, string> | undefined {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return undefined;
  const formatted = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    weekday: "short",
  }).formatToParts(date);
  return Object.fromEntries(formatted.map((part) => [part.type, part.value]));
}

/** 현지 날짜 `YYYY-MM-DD`. 날짜별로 묶거나 짧게 표시할 때 씁니다. */
export function localDateKey(iso: string, timeZone?: string): string {
  const value = parts(iso, timeZone);
  return value ? `${value.year}-${value.month}-${value.day}` : iso.slice(0, 10);
}

/** 현지 시각 `HH:mm` */
export function localTime(iso: string, timeZone?: string): string {
  const value = parts(iso, timeZone);
  return value ? `${value.hour}:${value.minute}` : iso.slice(11, 16);
}

const weekdays: Record<string, string> = {
  Sun: "일",
  Mon: "월",
  Tue: "화",
  Wed: "수",
  Thu: "목",
  Fri: "금",
  Sat: "토",
};

/** `2026년 9월 11일 (금)` 형태의 현지 날짜 */
export function localDateLabel(iso: string, timeZone?: string): string {
  const value = parts(iso, timeZone);
  if (!value) return iso.slice(0, 10);
  return `${Number(value.year)}년 ${Number(value.month)}월 ${Number(value.day)}일 (${weekdays[value.weekday] ?? ""})`;
}
