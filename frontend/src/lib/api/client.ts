import { API_BASE_URL } from "./config";
import { isSupabaseConfigured } from "../supabase/config";
import { createClient } from "../supabase/client";
import { parseSseFrames } from "./sse";
import {
  errorKindForStatus,
  messageForKind,
  parseRetryAfter,
  userMessageForResponse,
  type ApiErrorKind,
} from "./error-message";

/**
 * 응답 헤더가 올 때까지 기다리는 최대 시간.
 *
 * Ollama 모델 점검처럼 서버가 길게 일하는 호출이 있어 넉넉하게 둡니다. 느린 응답에 대한
 * 안내는 화면의 로딩 표시가 맡고, 이 값은 연결이 멈췄을 때의 안전망입니다.
 */
const REQUEST_TIMEOUT_MS = 150_000;

/** 업로드가 이 시간 동안 1바이트도 진행되지 않으면 멈춘 것으로 봅니다. */
const UPLOAD_STALL_TIMEOUT_MS = 60_000;

async function authHeaders(): Promise<Record<string, string>> {
  if (!isSupabaseConfigured) return {};
  const { data } = await createClient().auth.getSession();
  return data.session ? { Authorization: `Bearer ${data.session.access_token}` } : {};
}

/** 서버가 실패를 돌려줬을 때 화면이 구분해서 처리할 수 있는 오류 타입입니다. */
export class ApiError extends Error {
  /** 화면이 문구와 다음 행동을 고를 때 쓰는 실패 분류 */
  readonly kind: ApiErrorKind;
  /** 429일 때 서버가 알려준 대기 시간(초) */
  readonly retryAfter?: number;

  constructor(
    readonly status: number,
    message: string,
    /** 서버가 돌려준 원문. 사용자에게 그대로 보여주지 않습니다. */
    readonly detail?: unknown,
    options: { kind?: ApiErrorKind; retryAfter?: number } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.kind = options.kind ?? errorKindForStatus(status);
    this.retryAfter = options.retryAfter;
  }

  /** 재시도해볼 만한 실패인지 */
  get isRetryable(): boolean {
    return this.status === 0 || this.status === 429 || this.status >= 500;
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  let detail: unknown;

  try {
    detail = await response.json();
  } catch {
    // 본문이 JSON이 아니면 상태 코드 기반 문구를 씁니다.
  }

  return new ApiError(response.status, userMessageForResponse(response.status, detail), detail, {
    retryAfter: parseRetryAfter(response.headers.get("Retry-After")),
  });
}

/** 연결 자체가 실패했을 때. 오프라인이면 사용자가 고칠 수 있으므로 따로 알립니다. */
function connectionError(cause?: unknown): ApiError {
  const kind: ApiErrorKind =
    typeof navigator !== "undefined" && navigator.onLine === false ? "offline" : "network";
  return new ApiError(0, messageForKind(kind), cause, { kind });
}

/**
 * 세션이 만료되면 "다시 시도"로는 풀리지 않으므로 로그인 화면으로 보냅니다.
 * 로그인 뒤 보던 화면으로 돌아오도록 현재 경로를 `next`로 넘깁니다.
 */
function redirectToLogin(): void {
  if (typeof window === "undefined" || !isSupabaseConfigured) return;
  if (window.location.pathname.startsWith("/login")) return;
  const next = `${window.location.pathname}${window.location.search}`;
  window.location.assign(`/login?reason=expired&next=${encodeURIComponent(next)}`);
}

async function request(path: string, init?: RequestInit, authenticated = true): Promise<Response> {
  let response: Response;

  // 호출부의 취소와 시간 초과를 하나의 signal로 묶습니다.
  const controller = new AbortController();
  const callerSignal = init?.signal ?? undefined;
  const forwardAbort = () => controller.abort();
  if (callerSignal?.aborted) controller.abort();
  else callerSignal?.addEventListener("abort", forwardAbort, { once: true });
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, REQUEST_TIMEOUT_MS);

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { ...(authenticated ? await authHeaders() : {}), ...init?.headers },
    });
  } catch (error) {
    if (timedOut) throw new ApiError(0, messageForKind("timeout"), error, { kind: "timeout" });
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw connectionError(error);
  } finally {
    // 헤더를 받은 뒤에는 본문(스트리밍 포함)을 시간제한 없이 읽습니다.
    clearTimeout(timer);
  }

  if (!response.ok) {
    if (response.status === 401 && authenticated) redirectToLogin();
    throw await toApiError(response);
  }
  return response;
}

/** JSON 본문을 주고받는 일반 호출 */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });

  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

/** Authenticated binary download (for reviewed source exports). */
export async function apiBlob(path: string, init?: RequestInit): Promise<Blob> {
  return (await request(path, init)).blob();
}

/** Public demo reads never attach a workspace session token. */
export async function apiPublicFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(path, init, false);
  return (await response.json()) as T;
}

export async function apiPublicBlob(path: string, init?: RequestInit): Promise<Blob> {
  return (await request(path, init, false)).blob();
}

/** 업로드 호출에 공통으로 붙는 옵션 */
export type UploadOptions = {
  signal?: AbortSignal;
  /** 0..1. 전송 바이트 기준이며 서버 처리 시간은 포함하지 않습니다. */
  onProgress?: (ratio: number) => void;
};

/**
 * multipart/form-data 업로드.
 *
 * fetch에는 업로드 진행률 이벤트가 없어 XMLHttpRequest를 씁니다.
 * Content-Type은 브라우저가 boundary와 함께 붙이므로 직접 지정하지 않습니다.
 */
export async function apiUpload<T>(
  path: string,
  body: FormData,
  options: UploadOptions = {},
): Promise<T> {
  const { signal, onProgress } = options;
  const headers = await authHeaders();

  return new Promise<T>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}${path}`);
    xhr.responseType = "json";
    Object.entries(headers).forEach(([name, value]) => xhr.setRequestHeader(name, value));

    // 전송이 멈추면 끝없이 기다리지 않도록, 진행이 있을 때마다 타이머를 다시 겁니다.
    let stalled = false;
    let stallTimer: ReturnType<typeof setTimeout> | undefined;
    const armStallTimer = () => {
      clearTimeout(stallTimer);
      stallTimer = setTimeout(() => {
        stalled = true;
        xhr.abort();
      }, UPLOAD_STALL_TIMEOUT_MS);
    };
    armStallTimer();
    xhr.addEventListener("loadend", () => clearTimeout(stallTimer));

    xhr.upload.addEventListener("progress", (event) => {
      armStallTimer();
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    });
    // 전송이 끝난 뒤 서버가 파일을 확인하는 동안에는 진행 이벤트가 없습니다.
    xhr.upload.addEventListener("load", () => clearTimeout(stallTimer));

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(1);
        resolve(xhr.response as T);
        return;
      }

      const detail: unknown = xhr.response;
      if (xhr.status === 401) redirectToLogin();
      reject(
        new ApiError(xhr.status, userMessageForResponse(xhr.status, detail), detail, {
          retryAfter: parseRetryAfter(xhr.getResponseHeader("Retry-After")),
        }),
      );
    });

    xhr.addEventListener("error", () => reject(connectionError()));
    xhr.addEventListener("abort", () =>
      reject(
        stalled
          ? new ApiError(0, messageForKind("timeout"), undefined, { kind: "timeout" })
          : new DOMException("Aborted", "AbortError"),
      ),
    );

    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(body);
  });
}

/** Server-Sent Events 스트림을 한 줄씩 파싱해 넘겨줍니다. */
export async function* apiStream(
  path: string,
  init: RequestInit,
): AsyncGenerator<unknown, void, undefined> {
  const response = await request(path, {
    ...init,
    headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...init.headers },
  });

  if (!response.body) throw new ApiError(0, "스트리밍 응답을 읽지 못했습니다.");

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  const cancel = () => { void reader.cancel().catch(() => {}); };
  init.signal?.addEventListener("abort", cancel, { once: true });
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const parsed = parseSseFrames(buffer + value);
      buffer = parsed.remainder;
      for (const payload of parsed.payloads) yield JSON.parse(payload);
      if (parsed.done) return;
    }
    for (const payload of parseSseFrames(`${buffer}\n\n`).payloads) yield JSON.parse(payload);
  } finally {
    init.signal?.removeEventListener("abort", cancel);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
