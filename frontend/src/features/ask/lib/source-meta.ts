/**
 * 근거 카드에 적는 종류와 위치입니다. 회의는 근거가 시작되는 시각을 함께 적습니다.
 * `timestamp`는 녹음 시작부터 센 초 단위입니다(`AnswerSource.timestamp`).
 */
export function formatSourceMeta(kind: "meeting" | "document", timestamp?: number): string {
  if (kind !== "meeting") return "문서";
  if (timestamp === undefined || !Number.isFinite(timestamp) || timestamp < 0) return "회의";
  return `회의 · ${formatOffset(timestamp)}`;
}

/** 초를 `mm:ss`로, 한 시간을 넘기면 `h:mm:ss`로 적습니다. */
export function formatOffset(seconds: number): string {
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = String(total % 60).padStart(2, "0");
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}`
    : `${String(minutes).padStart(2, "0")}:${rest}`;
}
