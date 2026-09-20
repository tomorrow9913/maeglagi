/**
 * 화면에서 공유하는 최소 도메인 타입입니다.
 *
 * API가 붙으면 `contracts/openapi.yaml`에서 생성한 타입이 기준이 되고,
 * 이 파일은 생성 타입을 재export 하는 얇은 층으로 줄입니다.
 */

/** 워크스페이스에 올라온 원본 자료의 종류 */
export type SourceKind = "document" | "meeting";

/** 업로드 이후 비동기 파이프라인의 상태 */
export type ProcessingStatus = "queued" | "enqueue_pending" | "processing" | "awaiting_review" | "awaiting_agent" | "succeeded" | "failed";

/** Ontology에서 Timeline과 Graph에 함께 쓰는 항목 종류 */
export type ContextKind = "decision" | "issue" | "task" | "event";

export const contextKindLabel: Record<ContextKind, string> = {
  decision: "결정",
  issue: "이슈",
  task: "할 일",
  event: "이벤트",
};

export const processingStatusLabel: Record<ProcessingStatus, string> = {
  queued: "대기 중",
  enqueue_pending: "분석 연결 중",
  processing: "처리 중",
  awaiting_review: "대본 검토 필요",
  awaiting_agent: "에이전트 작업 대기",
  succeeded: "완료",
  failed: "실패",
};
