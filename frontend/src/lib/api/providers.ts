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
    id: "openai",
    displayName: "OpenAI",
    capabilities: ["chat", "embedding", "structuredOutput", "transcription", "models"],
    configured: false,
    models: [],
  },
  {
    id: "anthropic",
    displayName: "Anthropic (Claude)",
    capabilities: ["chat", "models"],
    configured: false,
    models: [],
  },
  {
    id: "nvidia",
    displayName: "NVIDIA NIM",
    capabilities: ["chat", "models"],
    configured: false,
    models: [],
  },
] as const;

/**
 * 서버 capability 키를 사용자가 아는 기능 이름으로 옮긴 표입니다.
 * provider가 어떤 기능을 지원하지 않으면 무엇이 안 되는지 미리 알려주는 데 씁니다.
 */
export const PROVIDER_FEATURES = [
  {
    capability: "embedding",
    label: "문서·회의 검색",
    unsupported: "문서와 회의 내용을 검색할 수 없습니다.",
  },
  {
    capability: "structuredOutput",
    label: "결정·담당자 그래프 추출",
    unsupported: "결정, 담당자, 관계를 뽑아 그래프로 만들 수 없습니다.",
  },
  {
    capability: "transcription",
    label: "회의 녹음 받아쓰기",
    unsupported: "녹음 파일은 받아쓸 수 없습니다. 브라우저 받아쓰기 대본은 그대로 쓸 수 있습니다.",
  },
] as const;

/** 지원하는 기능이 가장 많은 provider. 처음 고르는 값이 되도록 기능이 빠지지 않는 쪽을 앞세웁니다. */
export function pickDefaultProvider(providers: readonly AiProvider[]): LlmProvider {
  const score = (provider: AiProvider) =>
    PROVIDER_FEATURES.filter((feature) => provider.capabilities.includes(feature.capability))
      .length;
  const best = providers.reduce<AiProvider | undefined>(
    (winner, provider) => (!winner || score(provider) > score(winner) ? provider : winner),
    undefined,
  );
  return best?.id ?? "";
}

export function providerKeyPlaceholder(provider: LlmProvider): string {
  if (provider === "anthropic") return "sk-ant-...";
  if (provider === "nvidia") return "nvapi-...";
  return "sk-...";
}
