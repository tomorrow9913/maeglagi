import { toUserMessage } from "@/lib/api/error-message";

/**
 * AI 연결 삭제·기본 지정이 거절됐을 때의 문구.
 *
 * 백엔드는 이유를 영어 `detail`로만 구분해 주고, 공통 오류 처리는 그 원문을 상태 코드별
 * 기본 문구로 바꿉니다. 여기서는 다음 행동이 이유마다 다르므로 원문을 읽어 문구를 고릅니다.
 * 원문 자체는 화면에 내보내지 않습니다.
 */

export const CREDENTIAL_IN_USE_MESSAGE =
  "이 연결은 워크스페이스의 모델에 쓰이고 있어 삭제할 수 없습니다. 해당 워크스페이스의 모델을 먼저 바꿔 주세요.";
export const CREDENTIAL_DEFAULT_MESSAGE =
  "기본 연결은 다른 연결을 기본으로 지정한 뒤 삭제할 수 있습니다.";
export const CREDENTIAL_LAST_FOR_PROVIDER_MESSAGE =
  "워크스페이스가 이 AI 공급자의 모델을 쓰고 있어 마지막 연결은 삭제할 수 없습니다. 해당 워크스페이스의 모델을 먼저 바꿔 주세요.";

function statusOf(error: unknown): number | undefined {
  if (!error || typeof error !== "object" || !("status" in error)) return undefined;
  const status = (error as { status: unknown }).status;
  return typeof status === "number" ? status : undefined;
}

/** `ApiError.detail`은 응답 본문 전체(`{ detail: "..." }`)입니다. */
function serverDetail(error: unknown): string {
  if (!error || typeof error !== "object" || !("detail" in error)) return "";
  const body = (error as { detail: unknown }).detail;
  if (typeof body === "string") return body;
  if (!body || typeof body !== "object" || !("detail" in body)) return "";
  const detail = (body as { detail: unknown }).detail;
  return typeof detail === "string" ? detail : "";
}

export function credentialDeleteErrorMessage(error: unknown): string {
  const status = statusOf(error);
  if (status === 409) {
    const detail = serverDetail(error);
    if (detail.includes("selected by a workspace model")) return CREDENTIAL_IN_USE_MESSAGE;
    if (detail.includes("another default")) return CREDENTIAL_DEFAULT_MESSAGE;
    if (detail.includes("last active credential")) return CREDENTIAL_LAST_FOR_PROVIDER_MESSAGE;
    return "이 연결은 지금 삭제할 수 없습니다. 연결 목록을 새로 불러온 뒤 다시 시도해 주세요.";
  }
  if (status === 404) return "이미 삭제된 연결입니다.";
  return toUserMessage(error, "AI 연결을 삭제하지 못했습니다.");
}

export function credentialDefaultErrorMessage(error: unknown): string {
  const status = statusOf(error);
  if (status === 409) {
    return "확인이 필요한 연결은 기본으로 지정할 수 없습니다. 수정에서 연결을 다시 확인해 주세요.";
  }
  if (status === 404) return "연결을 찾지 못했습니다. 목록을 새로 불러와 주세요.";
  return toUserMessage(error, "기본 연결을 바꾸지 못했습니다.");
}

/** 서버의 연결 상태 값을 화면 문구로 바꿉니다. 지금 백엔드가 쓰는 값은 "active"뿐입니다. */
export function credentialStatusInfo(status: string): {
  label: string;
  tone: "success" | "warning";
} {
  return status === "active"
    ? { label: "활성", tone: "success" }
    : { label: "확인 필요", tone: "warning" };
}
