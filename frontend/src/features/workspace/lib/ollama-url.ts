/**
 * Ollama 서버 주소를 서버에 보내기 전에 모양만 확인하고, 서버가 거절했을 때 보여줄 문구를 고릅니다.
 *
 * 백엔드 `normalize_ollama_url`과 같은 기준(http/https, 호스트 필수, 계정 정보·query·fragment 금지)을
 * 씁니다. 입력 중인 `https://` 같은 값으로 서버를 호출해 빨간 오류가 깜빡이는 일을 막으려는 것입니다.
 */

export const OLLAMA_URL_SCHEME_MESSAGE = "http:// 또는 https://로 시작하는 주소를 입력해 주세요.";
export const OLLAMA_URL_INCOMPLETE_MESSAGE =
  "주소를 끝까지 입력해 주세요. 예: https://ollama.example.com";
export const OLLAMA_URL_EXTRA_MESSAGE = "주소에 계정 정보나 ?, # 뒤의 값은 넣을 수 없습니다.";

/** 모양이 맞으면 undefined, 아니면 입력란 아래에 보여줄 안내 문구를 돌려줍니다. 빈 값은 호출부가 다룹니다. */
export function ollamaUrlShapeError(value: string): string | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  if (!/^https?:\/\//i.test(trimmed)) return OLLAMA_URL_SCHEME_MESSAGE;
  let url: URL;
  try {
    url = new URL(trimmed);
  } catch {
    return OLLAMA_URL_INCOMPLETE_MESSAGE;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return OLLAMA_URL_SCHEME_MESSAGE;
  if (!url.hostname) return OLLAMA_URL_INCOMPLETE_MESSAGE;
  if (url.username || url.password || url.search || url.hash || /[?#\\\s]/.test(trimmed)) {
    return OLLAMA_URL_EXTRA_MESSAGE;
  }
  return undefined;
}

/** 주소만 보고 알 수 있는 loopback·사설 대역인지. 이름으로 된 주소는 어디로 풀릴지 알 수 없어 false입니다. */
export function isLocalOrPrivateHost(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (host === "localhost" || host.endsWith(".localhost") || host === "0.0.0.0") return true;
  if (host === "::1" || host === "::" || /^f[cd][0-9a-f]{2}:/.test(host) || host.startsWith("fe80:")) {
    return true;
  }
  const octets = /^(\d{1,3})\.(\d{1,3})\.\d{1,3}\.\d{1,3}$/.exec(host);
  if (!octets) return false;
  const [first, second] = [Number(octets[1]), Number(octets[2])];
  return (
    first === 127 ||
    first === 10 ||
    (first === 192 && second === 168) ||
    (first === 172 && second >= 16 && second <= 31) ||
    (first === 169 && second === 254)
  );
}

const REASON_MESSAGES: Record<string, string> = {
  invalid_url: "Ollama 서버 주소 형식을 확인해 주세요.",
  address_not_permitted:
    "맥락이 서버에서 접근할 수 없는 주소입니다. localhost나 사설 IP는 쓸 수 없어요.",
  https_required: "공개 주소는 https만 쓸 수 있습니다.",
  unreachable: "서버가 응답하지 않습니다. 주소와 방화벽을 확인해 주세요.",
};

/** 검증 응답 본문에 영어로 실려 오는 주소 형식 오류. 그대로 보여주지 않습니다. */
const INVALID_URL_DETAILS = ["Invalid Ollama baseUrl", "Ollama baseUrl is required"];

/** 지금 백엔드가 Ollama 연결 실패에 돌려주는 단 하나의 문구. 이유를 구분하지 않습니다. */
const GENERIC_SERVER_MESSAGE = "Ollama 서버 주소 또는 연결을 확인해 주세요.";

const HANGUL = /[가-힣]/;

/**
 * Ollama 연결 확인이 실패했을 때 주소 입력란 아래에 보여줄 문구.
 *
 * 서버가 `reason`을 주면 그 이유를 그대로 말합니다. 지금 백엔드는 접근 불가 주소·https 필요·
 * 무응답을 한 문구로 합쳐 돌려주므로, 그때는 단정하지 않고 주소 모양에서 확실히 말할 수 있는
 * 규칙만 덧붙입니다.
 */
export function ollamaFailureMessage(
  result: { message: string; reason?: string },
  baseUrl: string,
): string {
  if (result.reason && REASON_MESSAGES[result.reason]) return REASON_MESSAGES[result.reason];
  if (INVALID_URL_DETAILS.includes(result.message)) return REASON_MESSAGES.invalid_url;
  // 키 형식 오류처럼 서버가 사용자용으로 쓴 다른 한국어 문구는 그대로 둡니다.
  if (HANGUL.test(result.message) && result.message !== GENERIC_SERVER_MESSAGE) return result.message;

  const base = "Ollama 서버에 연결하지 못했습니다. 주소와 방화벽을 확인해 주세요.";
  let url: URL;
  try {
    url = new URL(baseUrl.trim());
  } catch {
    return base;
  }
  if (isLocalOrPrivateHost(url.hostname)) {
    return `${base} localhost나 사설 IP는 서버 관리자가 허용한 경우에만 쓸 수 있어요.`;
  }
  if (url.protocol === "http:") return `${base} ${REASON_MESSAGES.https_required}`;
  return base;
}

/** `htt`, `https:/`처럼 아직 scheme을 치는 중인지. 이때는 경고색 없이 안내만 보여줍니다. */
export function isTypingScheme(value: string): boolean {
  const typed = value.trim().toLowerCase();
  return typed.length > 0 && ("https://".startsWith(typed) || "http://".startsWith(typed));
}

/** 서버가 만든 확인 문구의 용어를 화면 용어(AI 공급자, API key)로 맞춥니다. 한글이 없으면 fallback을 씁니다. */
export function normalizeValidationCopy(message: string, fallback: string): string {
  if (!HANGUL.test(message)) return fallback;
  return message.replace(/provider/gi, "AI 공급자").replaceAll("API 키", "API key");
}
