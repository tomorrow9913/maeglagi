import type { ProcessingStage, SourceKind } from "@/lib/api";

export const stageLabel: Record<ProcessingStage, string> = {
  uploaded: "업로드",
  transcribing: "음성 인식",
  awaiting_review: "대본 검토",
  confirmed: "분석 연결",
  analyzing: "분석",
  graphing: "그래프 반영",
  completed: "완료",
};

/**
 * 소스 종류별로 거치는 단계 순서입니다.
 *
 * mock의 `stageSequence`와 같은 순서를 유지해야 합니다. 실 API도 이
 * 순서대로 `stage`를 올려줍니다.
 */
const sequence: Record<SourceKind, ProcessingStage[]> = {
  document: ["uploaded", "analyzing", "graphing", "completed"],
  meeting: ["uploaded", "transcribing", "awaiting_review", "confirmed", "analyzing", "graphing", "completed"],
};
const browserSequence: ProcessingStage[] = ["uploaded", "awaiting_review", "confirmed", "analyzing", "graphing", "completed"];

export function stagesFor(
  kind: SourceKind,
  transcriptSource?: "server" | "browser",
): ProcessingStage[] {
  return transcriptSource === "browser" ? browserSequence : sequence[kind];
}

/** 진행 표시에서 현재 단계가 몇 번째인지. 모르는 값이면 0을 돌려줍니다. */
export function stageIndexOf(
  kind: SourceKind,
  stage: ProcessingStage,
  transcriptSource?: "server" | "browser",
): number {
  return Math.max(stagesFor(kind, transcriptSource).indexOf(stage), 0);
}
