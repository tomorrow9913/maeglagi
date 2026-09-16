import type { AiProvider, LlmProvider } from "./types";

/**
 * workspace가 아직 없는 최초 생성 화면용 bootstrap catalog입니다.
 *
 * 생성 이후에는 항상 workspace provider catalog API를 사용합니다. 백엔드에
 * provider가 추가되면 설정 화면에는 자동으로 나타나며, 이 목록은 별도의
 * bootstrap endpoint가 생길 때까지만 최초 키 등록 선택지를 제공합니다.
 */
export const BOOTSTRAP_AI_PROVIDERS: readonly AiProvider[] = [
  {
    id: "anthropic",
    displayName: "Anthropic (Claude)",
    capabilities: ["chat"],
    configured: false,
    models: [],
  },
  {
    id: "nvidia",
    displayName: "NVIDIA NIM",
    capabilities: ["chat"],
    configured: false,
    models: [],
  },
  {
    id: "openai",
    displayName: "OpenAI",
    capabilities: ["chat"],
    configured: false,
    models: [],
  },
] as const;

export const DEFAULT_BOOTSTRAP_PROVIDER = BOOTSTRAP_AI_PROVIDERS[0].id;

export function providerKeyPlaceholder(provider: LlmProvider): string {
  if (provider === "anthropic") return "sk-ant-...";
  if (provider === "nvidia") return "nvapi-...";
  return "sk-...";
}
