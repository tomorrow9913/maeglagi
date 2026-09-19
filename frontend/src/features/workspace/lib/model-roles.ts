import type { ModelOption, ModelRole, ModelSelections, RoleModels } from "@/lib/api";

/**
 * 모델 용도의 표시 문구. 서버는 role 키만 내려주므로 문구는 프론트가 가집니다.
 * `unavailable`은 이 키로 쓸 수 있는 모델이 하나도 없을 때 무엇이 안 되는지 알려줍니다.
 */
export const modelRoleInfo: Record<
  ModelRole,
  { label: string; description: string; unavailable: string }
> = {
  answer: {
    label: "답변 생성",
    description: "Ask 화면에서 질문에 답하는 모델입니다.",
    unavailable: "질문에 답할 수 없습니다.",
  },
  extraction: {
    label: "분석·그래프 추출",
    description: "회의와 문서에서 결정·이슈·담당자를 뽑아 그래프와 현재 상황을 만드는 모델입니다.",
    unavailable: "결정·담당자·관계를 뽑아 그래프와 현재 상황을 만들 수 없습니다.",
  },
  embedding: {
    label: "검색 임베딩",
    description: "문서와 회의 내용을 검색할 수 있게 벡터로 바꾸는 모델입니다.",
    unavailable: "문서와 회의 내용을 검색할 수 없습니다.",
  },
  transcription: {
    label: "녹음 받아쓰기",
    description:
      "회의 녹음 파일을 글로 옮기는 모델입니다. 브라우저 받아쓰기에는 필요하지 않습니다.",
    unavailable: "녹음 파일은 받아쓸 수 없습니다. 브라우저 받아쓰기 대본은 그대로 쓸 수 있습니다.",
  },
};

export function optionKey(option: ModelOption): string {
  return `${option.provider}/${option.model}`;
}

/** 저장된 선택이 있으면 그것을, 없으면 서버가 추천한 첫 옵션을 미리 고릅니다. */
export function initialSelections(roles: RoleModels[]): ModelSelections {
  const selections: ModelSelections = {};
  for (const entry of roles) {
    const chosen = entry.selected ?? entry.options[0];
    if (chosen) selections[entry.role] = chosen;
  }
  return selections;
}

/** 두 선택이 같은지. 설정 화면에서 바뀐 용도만 저장하려고 비교합니다. */
export function sameSelection(a: ModelOption | undefined, b: ModelOption | undefined): boolean {
  return a?.provider === b?.provider && a?.model === b?.model;
}
