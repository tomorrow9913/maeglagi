import { API_BASE_URL } from "./config";
import { isSupabaseConfigured } from "../supabase/config";
import { createClient } from "../supabase/client";

async function authHeaders(): Promise<Record<string, string>> {
  if (!isSupabaseConfigured) return {};
  const { data } = await createClient().auth.getSession();
  return data.session ? { Authorization: `Bearer ${data.session.access_token}` } : {};
}

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

async function request(path: string, init?: RequestInit, authenticated = true): Promise<Response> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { ...(authenticated ? await authHeaders() : {}), ...init?.headers },
    });
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

    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    });

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(1);
        resolve(xhr.response as T);
        return;
      }

      const detail: unknown = xhr.response;
      const message =
        detail &&
        typeof detail === "object" &&
        typeof (detail as { detail?: unknown }).detail === "string"
          ? (detail as { detail: string }).detail
          : `업로드에 실패했습니다 (${xhr.status})`;
      reject(new ApiError(xhr.status, message, detail));
    });

    xhr.addEventListener("error", () => reject(new ApiError(0, "서버에 연결하지 못했습니다.")));
    xhr.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));

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
