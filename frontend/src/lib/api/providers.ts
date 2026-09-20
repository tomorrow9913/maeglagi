import type { AiProvider, LlmProvider } from "./types";

/**
 * 서버 카탈로그(`api.listProviders`)를 받지 못했을 때만 쓰는 대비 목록입니다.
 *
 * 화면은 항상 서버 카탈로그를 먼저 쓰고, 백엔드가 응답하지 않을 때 최초 생성
 * 화면이 비지 않도록 이 목록으로 물러섭니다. capability는 백엔드 provider
 * registry의 실제 값과 같게 유지해야 하며, mock 구현도 이 목록을 그대로 씁니다.
 */
export const BOOTSTRAP_AI_PROVIDERS: readonly AiProvider[] = [
  {
    id: "ollama",
    displayName: "Ollama",
    authMode: "optionalApiKey",
    requiresBaseUrl: true,
    capabilities: ["chat", "embedding", "structuredOutput", "models"],
    configured: false,
    models: [],
  },
  {
    id: "openai",
    displayName: "OpenAI",
    capabilities: ["chat", "embedding", "structuredOutput", "transcription", "models"],
    configured: false,
    models: [],
    defaultModels: {
      answer: "gpt-4o-mini",
      extraction: "gpt-4o-mini",
      embedding: "text-embedding-3-small",
      transcription: "whisper-1",
    },
  },
  {
    id: "anthropic",
    displayName: "Anthropic (Claude)",
    capabilities: ["chat", "models"],
    configured: false,
    models: [],
    defaultModels: { answer: "claude-haiku-4-5", extraction: "claude-haiku-4-5" },
  },
  {
    id: "nvidia",
    displayName: "NVIDIA NIM",
    capabilities: ["chat", "models"],
    configured: false,
    models: [],
    defaultModels: {
      answer: "meta/llama-3.1-8b-instruct",
      extraction: "meta/llama-3.1-8b-instruct",
    },
  },
] as const;

/**
 * 처음 고를 provider. 서버가 준 순서의 첫 번째를 씁니다.
 *
 * 무엇이 되고 안 되는지는 provider가 아니라 그 키로 쓸 수 있는 모델에 달려 있어서,
 * 여기서는 기능으로 순위를 매기지 않습니다. 키를 넣은 뒤 모델 선택 단계에서 용도별로 알려줍니다.
 */
export function pickDefaultProvider(providers: readonly AiProvider[]): LlmProvider {
  return providers[0]?.id ?? "";
}

/** Ollama 주소는 사용자별 연결이므로 서버 환경 변수 유무와 관계없이 선택할 수 있습니다. */
export function withOllamaProvider(providers: readonly AiProvider[]): AiProvider[] {
  const ollama = BOOTSTRAP_AI_PROVIDERS.find((provider) => provider.id === "ollama")!;
  return providers.some((provider) => provider.id === "ollama")
    ? providers.map((provider) => provider.id === "ollama"
      ? { ...provider, authMode: "optionalApiKey", requiresBaseUrl: true }
      : provider)
    : [...providers, ollama];
}

export function providerKeyPlaceholder(provider: LlmProvider): string {
  if (provider === "ollama") return "선택 사항: 서버에서 요구하는 API key";
  if (provider === "anthropic") return "sk-ant-...";
  if (provider === "nvidia") return "nvapi-...";
  return "sk-...";
}
