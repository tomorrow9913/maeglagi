/** AI 연결 이름 입력란의 예시. 공급자마다 어울리는 이름이 달라 따로 둡니다. */
export function connectionLabelPlaceholder(provider: string): string {
  if (provider === "ollama") return "예: 사무실 Ollama 서버";
  if (provider === "openai") return "예: 회사 OpenAI 계정";
  if (provider === "anthropic") return "예: 회사 Anthropic 계정";
  if (provider === "nvidia") return "예: 팀 NVIDIA NIM";
  return "예: 팀 공용 연결";
}

/** 이 서비스에서 "AI 연결"이 무엇인지 처음 보는 사람에게 한 문장으로 알려줍니다. */
export const AI_CONNECTION_EXPLAINER =
  "AI 연결은 OpenAI·Anthropic 같은 AI 공급자의 API key나 Ollama 서버 주소를 계정에 저장해 둔 것입니다. 사용한 만큼의 요금은 그 API key의 주인에게 청구됩니다.";

export const DEFAULT_CONNECTION_EXPLAINER =
  "기본 연결은 새 워크스페이스를 만들 때 먼저 선택되는 연결입니다.";
