import { API_BASE_URL } from "./config";

/** 서버가 실패를 돌려줬을 때 화면이 구분해서 처리할 수 있는 오류 타입입니다. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** 재시도해볼 만한 실패인지 */
  get isRetryable(): boolean {
    return this.status === 0 || this.status === 429 || this.status >= 500;
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  let detail: unknown;
  let message = `요청에 실패했습니다 (${response.status})`;

  try {
    detail = await response.json();
    if (detail && typeof detail === "object" && "detail" in detail) {
      const value = (detail as { detail: unknown }).detail;
      if (typeof value === "string") message = value;
    }
  } catch {
    // 본문이 JSON이 아니면 상태 코드 기반 메시지를 그대로 씁니다.
  }

  return new ApiError(response.status, message, detail);
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "서버에 연결하지 못했습니다.", error);
  }

  if (!response.ok) throw await toApiError(response);
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

/** multipart/form-data 업로드. Content-Type은 브라우저가 boundary와 함께 붙입니다. */
export async function apiUpload<T>(path: string, body: FormData, signal?: AbortSignal): Promise<T> {
  const response = await request(path, { method: "POST", body, signal });
  return (await response.json()) as T;
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
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += value;
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data:")) continue;

        const payload = trimmed.slice(5).trim();
        if (payload === "[DONE]") return;
        yield JSON.parse(payload);
      }
    }
  } finally {
    reader.releaseLock();
  }
}
