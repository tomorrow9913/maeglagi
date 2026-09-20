import type { ProcessingStatus, SourceKind } from "@/types/context";
import type { MeetingReview } from "@/lib/api";

/** One presentation policy for list, sidebar, and terminal job states. */
export function sourcePresentation(status: ProcessingStatus, kind: SourceKind) {
  const needsReview = status === "awaiting_review" || (kind === "meeting" && status === "failed");
  return {
    label: {
      queued: "대기 중",
      enqueue_pending: "분석 준비 중",
      processing: "처리 중",
      awaiting_review: "대본 검토 필요",
      awaiting_agent: "에이전트 작업 대기",
      succeeded: "완료",
      failed: "실패",
    }[status],
    tone: {
      queued: "neutral",
      enqueue_pending: "info",
      processing: "info",
      awaiting_review: "warning",
      awaiting_agent: "info",
      succeeded: "success",
      failed: "danger",
    }[status] as "neutral" | "info" | "warning" | "success" | "danger",
    canOpen: needsReview || status === "awaiting_agent" || status === "succeeded",
    needsReview,
    evidenceReady: status === "succeeded",
    isProcessing: status === "queued" || status === "enqueue_pending" || status === "processing",
  };
}

export function reviewConfirmationCopy(analysisMode?: "server" | "agent") {
  return analysisMode === "agent"
    ? {
        description: "프로젝트와 화자·내용을 저장한 뒤 확인해 주세요. 이후 연결한 에이전트가 분석 결과를 저장합니다.",
        button: "확인하고 에이전트 대기",
        success: "회의 대본을 확인했습니다. 에이전트 분석을 기다립니다.",
      }
    : {
        description: "프로젝트와 화자·내용을 저장한 뒤 확인하면 분석을 시작합니다.",
        button: "확인하고 분석 시작",
        success: "회의 대본을 확인했습니다. 분석을 시작합니다.",
      };
}

export function reviewDisplayState(review: Pick<MeetingReview, "reviewState" | "analysisMode" | "status">) {
  const readOnly = review.reviewState === "confirmed" || review.reviewState === "awaiting_agent";
  return {
    readOnly,
    waitingForAgent: review.status === "awaiting_agent",
    showServerRetry: readOnly && review.analysisMode !== "agent" && review.status === "failed",
    showAgentFailure: readOnly && review.analysisMode === "agent" && review.status === "failed",
  };
}
