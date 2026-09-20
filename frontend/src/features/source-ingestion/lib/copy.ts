import type { ProcessingJob } from "@/lib/api";

/**
 * 소스 업로드·처리 화면이 함께 쓰는 문구입니다.
 *
 * 같은 사건을 화면마다 다르게 말하지 않도록 한 곳에 둡니다. 말투는 docs/voice.md를
 * 따릅니다. 실패·상태는 합니다체 무주어, 다음 행동을 권할 때는 해요체입니다.
 */

export const UPLOAD_FAILED = "업로드에 실패했습니다.";
export const UPLOAD_CANCELLED = "업로드를 취소했습니다.";
export const UPLOAD_CONTINUES_IN_BACKGROUND = "창을 닫아도 업로드는 계속됩니다.";
export const RECORDING_UPLOAD_FAILED = "녹음을 올리지 못했습니다.";
export const CONNECTION_DELAYED = "상태 갱신이 지연되고 있습니다. 다시 연결하고 있어요.";
export const UNSAVED_CAPTURE_LEAVE_CONFIRM = "녹음이나 작성 중인 대본이 있습니다. 이동하면 사라집니다. 이동할까요?";
export const NO_PROJECTS_HINT = "아직 프로젝트가 없습니다. 참여자·프로젝트에서 만들어 보세요.";
export const FAILED_DOCUMENT_HINT = "분석에 실패했습니다. 같은 파일을 다시 올려 주세요.";
export const RECORDING_BLOCKS_FILE_UPLOAD = "녹음이나 대본 초안을 마친 뒤 문서·녹음 파일을 올릴 수 있습니다.";

/** 제목이 있으면 `"제목" `을 앞에 붙이고, 없으면 일반 명사로 시작합니다. */
function subject(title: string | undefined, fallback: string): string {
  const name = title?.trim();
  return name ? `"${name}"` : fallback;
}

export type SettledToast = {
  tone: "info" | "error" | "success";
  message: string;
  /** 토스트에 붙일 수 있는 다음 행동. 화면이 지원하는 것만 연결합니다. */
  action?: { kind: "review" | "timeline"; label: string };
};

/**
 * 처리 결과 토스트 문구. 소스 화면과 Ask의 업로드 창이 같은 문장을 씁니다.
 *
 * @param surface 성공했을 때 어디로 안내할지만 다릅니다.
 */
export function settledToast(
  job: Pick<ProcessingJob, "status" | "sourceKind">,
  title: string | undefined,
  surface: "sources" | "ask",
): SettledToast | undefined {
  if (job.status === "awaiting_agent") {
    return { tone: "info", message: `${subject(title, "소스")} 저장을 마쳤습니다. 에이전트 분석을 기다립니다.` };
  }
  if (job.status === "awaiting_review") {
    return {
      tone: "info",
      message: `${subject(title, "회의")} 대본 검토가 준비됐습니다.`,
      action: { kind: "review", label: "검토 열기" },
    };
  }
  if (job.status === "failed") {
    return job.sourceKind === "meeting"
      ? {
          tone: "error",
          message: `${subject(title, "회의")} 처리에 실패했습니다. 저장된 녹음이나 대본을 확인해 주세요.`,
          action: { kind: "review", label: "대본 열기" },
        }
      : { tone: "error", message: `${subject(title, "소스")} 분석에 실패했습니다. 같은 파일을 다시 올려 주세요.` };
  }
  if (job.status === "succeeded") {
    return surface === "sources"
      ? {
          tone: "success",
          message: `${subject(title, "소스")} 분석이 끝났습니다. Timeline에 반영됐습니다.`,
          action: { kind: "timeline", label: "Timeline 보기" },
        }
      : { tone: "success", message: `${subject(title, "소스")} 분석이 끝났습니다. Ask에서 질문해 보세요.` };
  }
  return undefined;
}
