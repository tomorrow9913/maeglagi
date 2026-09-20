import { toUserMessage } from "@/lib/api/error-message";

/**
 * 참여자·프로젝트 화면의 결과 문구입니다.
 *
 * 모든 저장에 같은 "저장했습니다."를 띄우면 무엇이 됐는지 알 수 없어서, 한 일을 그대로 적습니다.
 */
export const directoryToast = {
  projectCreated: (name: string) => `'${name}' 프로젝트를 만들었습니다.`,
  projectSaved: (name: string) => `'${name}' 프로젝트를 저장했습니다.`,
  projectArchived: (name: string) => `'${name}' 프로젝트를 보관했습니다.`,
  projectRestored: (name: string) => `'${name}' 프로젝트를 복원했습니다.`,
  personSaved: "참여자 정보를 저장했습니다.",
  personArchived: (name: string) => `'${name}' 참여자를 보관했습니다.`,
  personRestored: (name: string) => `'${name}' 참여자를 복원했습니다.`,
  personAdded: "참여자를 추가했습니다.",
  personMissing: "찾을 수 없는 참여자입니다.",
  projectMissing: "찾을 수 없는 프로젝트입니다.",
} as const;

type ApiErrorLike = { kind?: unknown; detail?: unknown };

function detailText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "detail" in detail) {
    const value = (detail as { detail: unknown }).detail;
    return typeof value === "string" ? value : "";
  }
  return "";
}

/**
 * 저장 실패를 토스트 문구로 바꿉니다.
 *
 * 409는 이 화면에서 두 가지입니다. 다른 곳에서 먼저 바뀐 경우(revision 충돌)와, 같은
 * 이메일의 참여자가 이미 있는 경우입니다. 다음 행동이 다르므로 문구를 나눕니다.
 * `ApiError`를 직접 import 하지 않고 모양만 확인해서 단위 테스트가 가볍게 돕니다.
 */
export function mutationErrorMessage(error: unknown): string {
  const candidate = (error ?? {}) as ApiErrorLike;

  if (candidate.kind === "conflict") {
    return /email/i.test(detailText(candidate.detail))
      ? "같은 이메일을 쓰는 참여자가 이미 있습니다. 이메일을 확인해 주세요."
      : "다른 곳에서 먼저 바뀌었습니다. 최신 내용으로 다시 열어 주세요.";
  }
  return toUserMessage(error, "요청을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.");
}
