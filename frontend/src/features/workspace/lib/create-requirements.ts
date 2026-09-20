/**
 * 새 워크스페이스를 만들기 전에 채워야 하는 조건.
 *
 * "만들기" 버튼의 비활성 조건과 버튼 위 안내 문구가 어긋나지 않도록, 둘 다 이 함수 하나에서
 * 나옵니다. 아직 채우지 못한 첫 조건의 문구를 돌려주고, 모두 채웠으면 undefined입니다.
 */
export type CreateRequirementState = {
  name: string;
  setupMode: "agent" | "service";
  /** 계정의 AI 연결 목록을 받았는지 */
  credentialsReady: boolean;
  credentialsFailed: boolean;
  /** 저장된 연결을 고르는 대신 새 연결을 입력하는 중인지 */
  addingConnection: boolean;
  connectionLabel: string;
  duplicateLabel: boolean;
  /** 서버 주소가 필요한 공급자(Ollama)인지 */
  needsBaseUrl: boolean;
  baseUrl: string;
  /** 새 연결은 확인을 통과했는지, 저장된 연결은 하나를 골랐는지 */
  isConnectionValid: boolean;
  modelsLoading: boolean;
  modelsFailed: boolean;
  hasRoles: boolean;
  selectionCount: number;
};

export function firstUnmetRequirement(state: CreateRequirementState): string | undefined {
  if (!state.name.trim()) return "워크스페이스 이름을 입력해 주세요.";
  if (state.setupMode === "agent") return undefined;

  if (state.credentialsFailed) return "AI 연결 목록을 불러와야 합니다. 위에서 다시 시도해 주세요.";
  if (!state.credentialsReady) return "저장된 AI 연결을 불러오고 있어요.";

  if (state.addingConnection) {
    if (!state.connectionLabel.trim()) return "연결 이름을 입력해 주세요.";
    if (state.duplicateLabel) return "다른 연결 이름을 입력해 주세요.";
    if (state.needsBaseUrl && !state.baseUrl.trim()) return "Ollama 서버 주소를 입력해 주세요.";
  }
  if (!state.isConnectionValid) {
    if (!state.addingConnection) return "AI 연결을 골라 주세요.";
    return state.needsBaseUrl
      ? "Ollama 서버 연결 확인이 끝나야 합니다."
      : "API key 확인이 끝나야 합니다.";
  }

  if (state.modelsLoading) return "모델 목록을 불러오고 있어요.";
  if (state.modelsFailed) return "모델 목록을 불러와야 합니다. 위에서 다시 시도해 주세요.";
  if (!state.hasRoles || state.selectionCount === 0) {
    return "이 연결로 쓸 수 있는 모델이 없습니다. 다른 AI 연결을 골라 주세요.";
  }
  return undefined;
}
