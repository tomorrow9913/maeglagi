import type { AnswerEvent, AnswerSource } from "@/lib/api";

/**
 * Ask 질문 한 건의 상태와, 그 상태를 바꾸는 순수 함수들입니다.
 *
 * 훅과 화면에서 떼어 둔 이유는 스트림 이벤트 처리·저장·복원을 브라우저 없이
 * 테스트하기 위해서입니다.
 */

export type AskTurnStatus = "streaming" | "done" | "error" | "aborted" | "no_evidence";

export type AskTurn = {
  id: string;
  question: string;
  /** 스트리밍으로 채워지는 답변 본문 */
  answer: string;
  sources: AnswerSource[];
  status: AskTurnStatus;
  errorMessage?: string;
  /** 오류 아래에 함께 보여줄 다음 행동. `settings`는 AI 연결을 등록하는 설정 화면입니다. */
  errorAction?: "settings";
};

/** 근거를 못 찾은 답변 본문. docs/voice.md 5장 5번과 같아야 합니다. */
export const NO_EVIDENCE_MESSAGE =
  "이 워크스페이스의 소스에서는 답할 근거를 찾지 못했어요. 관련 회의나 문서를 먼저 올려주세요.";
export const DISCONNECTED_MESSAGE = "연결이 끊겼습니다. 다시 시도해 주세요.";
export const ASK_FAILED_MESSAGE = "답변을 받지 못했습니다.";

/** 백엔드 질문 길이 제한(`AskRequest.question`)과 같은 값입니다. */
export const QUESTION_MAX_LENGTH = 2000;
/** 남은 글자 수가 이 값 이하로 내려가면 글자 수를 보여줍니다. */
export const QUESTION_COUNTER_THRESHOLD = 200;

export function newTurn(id: string, question: string): AskTurn {
  return { id, question, answer: "", sources: [], status: "streaming" };
}

/**
 * 근거 없음은 실패가 아니라 정상 결과입니다.
 * `code`를 보내지 않는 이전 서버는 문구로 구분합니다.
 */
export function isNoEvidenceEvent(event: { code?: string; message?: string }): boolean {
  return event.code === "no_evidence" || (event.message ?? "").includes("근거를 찾지 못했");
}

/** 스트림 이벤트 한 건을 반영합니다. 이미 끝난 질문은 바꾸지 않습니다. */
export function reduceTurn(turn: AskTurn, event: AnswerEvent): AskTurn {
  if (turn.status !== "streaming") return turn;
  switch (event.type) {
    case "sources":
      return { ...turn, sources: event.sources };
    case "token":
      return { ...turn, answer: turn.answer + event.text };
    case "done":
      return { ...turn, status: "done" };
    case "error":
      return isNoEvidenceEvent(event)
        ? { ...turn, status: "no_evidence" }
        : { ...turn, status: "error", errorMessage: event.message || ASK_FAILED_MESSAGE };
    default:
      return turn;
  }
}

/**
 * 스트림이 `done`/`error` 없이 끝났을 때 질문을 마무리합니다.
 *
 * 사용자가 멈춘 경우와 연결이 끊긴 경우 모두 받은 본문은 그대로 둡니다.
 */
export function settleTurn(turn: AskTurn, reason: "aborted" | "disconnected"): AskTurn {
  if (turn.status !== "streaming") return turn;
  return reason === "aborted"
    ? { ...turn, status: "aborted" }
    : { ...turn, status: "error", errorMessage: DISCONNECTED_MESSAGE };
}

export function failTurn(turn: AskTurn, message: string, action?: AskTurn["errorAction"]): AskTurn {
  if (turn.status !== "streaming") return turn;
  return { ...turn, status: "error", errorMessage: message, errorAction: action };
}

/** 답변 대기 줄의 문구. 근거가 먼저 도착하므로 그 뒤로는 찾는 중이라고 말하지 않습니다. */
export function waitingLabel(turn: Pick<AskTurn, "sources">): string {
  return turn.sources.length > 0
    ? "찾은 근거로 답변을 쓰고 있어요"
    : "관련 회의와 문서를 찾아보고 있어요";
}

/* ---------- sessionStorage 저장·복원 ---------- */

const STORAGE_VERSION = 1;
/** 한 워크스페이스에 남겨 두는 질문 수. 저장소 용량을 넘기지 않으려는 상한입니다. */
export const STORED_TURN_LIMIT = 30;

export function turnsStorageKey(workspaceId: string): string {
  return `maeglagi:ask:${workspaceId}`;
}

/** 끝난 질문만 저장합니다. 진행 중인 질문은 새로 열었을 때 이어받을 수 없습니다. */
export function serializeTurns(turns: AskTurn[]): string {
  const finished = turns.filter((turn) => turn.status !== "streaming").slice(-STORED_TURN_LIMIT);
  return JSON.stringify({ version: STORAGE_VERSION, turns: finished });
}

const RESTORABLE: ReadonlySet<string> = new Set(["done", "error", "aborted", "no_evidence"]);

function isSource(value: unknown): value is AnswerSource {
  if (!value || typeof value !== "object") return false;
  const source = value as Record<string, unknown>;
  return (
    typeof source.index === "number" &&
    typeof source.sourceId === "string" &&
    typeof source.title === "string" &&
    typeof source.excerpt === "string" &&
    (source.kind === "meeting" || source.kind === "document")
  );
}

function isTurn(value: unknown): value is AskTurn {
  if (!value || typeof value !== "object") return false;
  const turn = value as Record<string, unknown>;
  return (
    typeof turn.id === "string" &&
    typeof turn.question === "string" &&
    typeof turn.answer === "string" &&
    typeof turn.status === "string" &&
    RESTORABLE.has(turn.status) &&
    Array.isArray(turn.sources) &&
    turn.sources.every(isSource)
  );
}

/** 저장된 값을 읽습니다. 형식이 다르거나 깨진 값은 버리고, 진행 중 상태로는 되살리지 않습니다. */
export function parseTurns(raw: string | null | undefined): AskTurn[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return [];
    const { version, turns } = parsed as { version?: unknown; turns?: unknown };
    if (version !== STORAGE_VERSION || !Array.isArray(turns)) return [];
    return turns.filter(isTurn);
  } catch {
    return [];
  }
}

/* ---------- 스크롤 ---------- */

/** 이 거리 안에 있으면 사용자가 맨 아래를 보고 있다고 봅니다. */
export const NEAR_BOTTOM_PX = 120;

export function isNearBottom(
  metrics: { scrollTop: number; clientHeight: number; scrollHeight: number },
  threshold = NEAR_BOTTOM_PX,
): boolean {
  return metrics.scrollHeight - (metrics.scrollTop + metrics.clientHeight) <= threshold;
}
