/**
 * 서버 실패를 사용자에게 보여줄 한국어 문구로 바꿉니다.
 *
 * 백엔드 `detail`은 대부분 개발자용 영어 문장이라 그대로 띄우지 않습니다.
 * 한글이 들어 있는 `detail`만 사용자용 문구로 보고 통과시키고, 나머지는
 * 상태 코드별 기본 문구로 바꿉니다. 원문은 `ApiError.detail`에 남습니다.
 */

export type ApiErrorKind =
  | "offline"
  | "network"
  | "timeout"
  | "auth"
  | "forbidden"
  | "notFound"
  | "conflict"
  | "tooLarge"
  | "invalid"
  | "rateLimited"
  | "server"
  | "unknown";

const MESSAGES: Record<ApiErrorKind, string> = {
  offline: "인터넷 연결을 확인해 주세요.",
  network: "서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
  timeout: "서버 응답이 늦어지고 있습니다. 잠시 후 다시 시도해 주세요.",
  auth: "로그인이 만료됐습니다. 다시 로그인해 주세요.",
  forbidden: "이 작업을 할 권한이 없습니다.",
  notFound: "요청한 내용을 찾지 못했습니다.",
  conflict: "다른 곳에서 먼저 바뀌었습니다. 최신 내용을 불러온 뒤 다시 시도해 주세요.",
  tooLarge: "파일이 너무 큽니다.",
  invalid: "입력한 내용을 확인해 주세요.",
  rateLimited: "요청이 많아 잠시 멈췄습니다. 조금 뒤에 다시 시도해 주세요.",
  server: "서버에 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.",
  unknown: "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
};

export function errorKindForStatus(status: number): ApiErrorKind {
  if (status === 0) return "network";
  if (status === 401) return "auth";
  if (status === 403) return "forbidden";
  if (status === 404) return "notFound";
  if (status === 408 || status === 504) return "timeout";
  if (status === 409) return "conflict";
  if (status === 413) return "tooLarge";
  if (status === 400 || status === 422) return "invalid";
  if (status === 429) return "rateLimited";
  if (status >= 500) return "server";
  return "unknown";
}

export function messageForKind(kind: ApiErrorKind): string {
  return MESSAGES[kind];
}

const HANGUL = /[가-힣]/;

/** 응답 본문에서 사용자에게 보여도 되는 한국어 `detail`만 꺼냅니다. */
function koreanDetail(body: unknown): string | undefined {
  if (!body || typeof body !== "object" || !("detail" in body)) return undefined;
  const value = (body as { detail: unknown }).detail;
  return typeof value === "string" && HANGUL.test(value) ? value : undefined;
}

/** 상태 코드와 응답 본문으로 화면에 띄울 문구를 정합니다. */
export function userMessageForResponse(status: number, body: unknown): string {
  // 세션 만료는 서버 문구와 관계없이 다음 행동(다시 로그인)을 알려야 합니다.
  if (status === 401) return MESSAGES.auth;
  return koreanDetail(body) ?? MESSAGES[errorKindForStatus(status)];
}

/** `Retry-After` 헤더(초 또는 HTTP 날짜)를 초 단위로 읽습니다. */
export function parseRetryAfter(value: string | null, now = Date.now()): number | undefined {
  if (!value) return undefined;
  const seconds = Number(value);
  if (Number.isFinite(seconds)) return Math.max(0, Math.ceil(seconds));
  const date = Date.parse(value);
  return Number.isNaN(date) ? undefined : Math.max(0, Math.ceil((date - now) / 1000));
}

/**
 * catch한 값을 토스트나 인라인 문구로 바꿉니다.
 *
 * `ApiError`는 이미 사용자용 문구를 갖고 있습니다. 그 밖의 예외(브라우저 API,
 * 파싱 오류 등)는 영어 원문일 수 있으므로 한글이 없으면 `fallback`을 씁니다.
 */
export function toUserMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && HANGUL.test(error.message)) return error.message;
  return fallback;
}
