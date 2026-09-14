import type {
  AnswerSource,
  ProcessingStage,
  ContextItem,
  KnowledgeGraph,
  Source,
  SourceContent,
  SourceKind,
  Workspace,
} from "../types";

export const DEMO_WORKSPACE_ID = "demo";

export const workspaces: Workspace[] = [
  {
    id: DEMO_WORKSPACE_ID,
    name: "데모 워크스페이스",
    createdAt: "2026-09-08T09:00:00Z",
    sourceCount: 3,
  },
];

export const sources: Source[] = [
  {
    id: "src-kickoff",
    workspaceId: DEMO_WORKSPACE_ID,
    kind: "meeting",
    title: "9/8 제품 킥오프 회의",
    status: "succeeded",
    createdAt: "2026-09-08T10:30:00Z",
    durationSeconds: 2730,
  },
  {
    id: "src-prd",
    workspaceId: DEMO_WORKSPACE_ID,
    kind: "document",
    title: "맥락이 PRD v0.2.pdf",
    status: "succeeded",
    createdAt: "2026-09-09T02:10:00Z",
    sizeBytes: 486_233,
  },
  {
    id: "src-tech-review",
    workspaceId: DEMO_WORKSPACE_ID,
    kind: "meeting",
    title: "9/11 기술 검토 회의",
    status: "succeeded",
    createdAt: "2026-09-11T06:00:00Z",
    durationSeconds: 1980,
  },
];

export const sourceContents: SourceContent[] = [
  {
    sourceId: "src-kickoff",
    title: "9/8 제품 킥오프 회의",
    kind: "meeting",
    chunks: [
      {
        id: "src-kickoff#1",
        text: "정민규: PoC 범위는 회의 녹음과 문서 업로드 두 갈래로 갑니다. 슬랙 연동은 이번 범위에서 뺍니다.",
      },
      {
        id: "src-kickoff#2",
        text: "윤희원: 그러면 프론트는 Timeline, Graph, Ask 세 화면에 집중하겠습니다. 소스 업로드는 문서 먼저 붙이고 녹음을 이어서 붙입니다.",
      },
      {
        id: "src-kickoff#3",
        text: "정민규: 저장소는 PostgreSQL, MinIO, pgvector, Neo4j 네 가지로 확정합니다. 이건 Day 1에 세워둡니다.",
      },
    ],
  },
  {
    sourceId: "src-prd",
    title: "맥락이 PRD v0.2.pdf",
    kind: "document",
    chunks: [
      {
        id: "src-prd#1",
        text: "맥락이는 회의와 문서에 흩어진 결정을 연결해, 질문에 근거와 함께 답하는 Organizational Context Platform이다.",
      },
      {
        id: "src-prd#2",
        text: "답변은 근거가 부족하면 생성하지 않는다. 인용한 원문 위치를 항상 함께 제시한다.",
      },
    ],
  },
  {
    sourceId: "src-tech-review",
    title: "9/11 기술 검토 회의",
    kind: "meeting",
    chunks: [
      {
        id: "src-tech-review#1",
        text: "정민규: LLM은 BYOK로 받습니다. 키는 서버에서 암호화해 저장하고 응답으로는 절대 돌려주지 않습니다.",
      },
      {
        id: "src-tech-review#2",
        text: "윤희원: 검색은 벡터 단독으로는 근거가 약해서, 그래프 탐색을 붙인 hybrid retrieval로 갑니다.",
      },
    ],
  },
];

export const contextItems: ContextItem[] = [
  {
    id: "ctx-1",
    kind: "decision",
    title: "PoC 범위를 회의 녹음과 문서 업로드로 한정",
    summary: "슬랙·지라 연동은 이번 PoC에서 제외하고, 소스 두 갈래에 집중하기로 했습니다.",
    occurredAt: "2026-09-08T10:42:00Z",
    sourceIds: ["src-kickoff"],
  },
  {
    id: "ctx-2",
    kind: "decision",
    title: "저장소를 PostgreSQL·MinIO·pgvector·Neo4j 4종으로 확정",
    summary: "원문, 메타데이터, 임베딩, 그래프를 각각의 저장소가 맡습니다.",
    occurredAt: "2026-09-08T10:55:00Z",
    sourceIds: ["src-kickoff"],
  },
  {
    id: "ctx-3",
    kind: "issue",
    title: "벡터 검색만으로는 근거가 약함",
    summary: "질문이 여러 회의에 걸치면 관련 청크를 놓치는 사례가 나왔습니다.",
    occurredAt: "2026-09-11T06:20:00Z",
    sourceIds: ["src-tech-review"],
    supersededBy: "ctx-4",
  },
  {
    id: "ctx-4",
    kind: "decision",
    title: "Hybrid retrieval(벡터 + 그래프) 채택",
    summary: "벡터 검색 결과를 그래프 이웃으로 확장해 근거 후보를 넓힙니다.",
    occurredAt: "2026-09-11T06:35:00Z",
    sourceIds: ["src-tech-review"],
  },
  {
    id: "ctx-5",
    kind: "task",
    title: "BYOK 키 암호화 저장 구현",
    summary: "키는 저장 시 암호화하고 어떤 응답으로도 원문을 내보내지 않습니다.",
    occurredAt: "2026-09-11T06:48:00Z",
    sourceIds: ["src-tech-review"],
  },
  {
    id: "ctx-6",
    kind: "event",
    title: "PRD v0.2 공유",
    summary: "제품 정의와 답변 원칙을 문서로 정리해 공유했습니다.",
    occurredAt: "2026-09-09T02:10:00Z",
    sourceIds: ["src-prd"],
  },
];

export const knowledgeGraph: KnowledgeGraph = {
  nodes: [
    { id: "person-minkyu", type: "person", label: "정민규", degree: 4 },
    { id: "person-heewon", type: "person", label: "윤희원", degree: 4 },
    { id: "project-maeglagi", type: "project", label: "맥락이 PoC", degree: 5 },
    { id: "decision-scope", type: "decision", label: "PoC 범위 한정", degree: 2 },
    { id: "decision-hybrid", type: "decision", label: "Hybrid retrieval 채택", degree: 3 },
    { id: "task-byok", type: "task", label: "BYOK 키 암호화", degree: 2 },
    { id: "event-kickoff", type: "event", label: "9/8 킥오프", degree: 3 },
  ],
  edges: [
    { id: "e1", source: "person-minkyu", target: "event-kickoff", type: "participates_in" },
    { id: "e2", source: "person-heewon", target: "event-kickoff", type: "participates_in" },
    { id: "e3", source: "person-minkyu", target: "decision-scope", type: "decided" },
    { id: "e4", source: "decision-scope", target: "project-maeglagi", type: "relates_to" },
    { id: "e5", source: "person-heewon", target: "decision-hybrid", type: "decided" },
    { id: "e6", source: "decision-hybrid", target: "project-maeglagi", type: "relates_to" },
    { id: "e7", source: "task-byok", target: "person-minkyu", type: "assigned_to" },
    { id: "e8", source: "task-byok", target: "project-maeglagi", type: "relates_to" },
    { id: "e9", source: "decision-hybrid", target: "decision-scope", type: "supersedes" },
  ],
};

/** 질문 키워드 → 답변과 근거. 어디에도 걸리지 않으면 `fallbackAnswer`를 씁니다. */
export const answers: { match: RegExp; text: string; sources: AnswerSource[] }[] = [
  {
    match: /retrieval|검색|하이브리드|hybrid/i,
    text: "벡터 검색만으로는 여러 회의에 걸친 질문에서 근거를 놓친다는 문제가 9/11 기술 검토 회의에서 제기됐습니다[1]. 그래서 벡터 검색 결과를 그래프 이웃으로 확장하는 hybrid retrieval을 채택했습니다[1]. 이 방식은 근거를 항상 원문 위치와 함께 제시한다는 PRD 원칙과도 맞습니다[2].",
    sources: [
      {
        index: 1,
        sourceId: "src-tech-review",
        chunkId: "src-tech-review#2",
        kind: "meeting",
        title: "9/11 기술 검토 회의",
        excerpt:
          "검색은 벡터 단독으로는 근거가 약해서, 그래프 탐색을 붙인 hybrid retrieval로 갑니다.",
      },
      {
        index: 2,
        sourceId: "src-prd",
        chunkId: "src-prd#2",
        kind: "document",
        title: "맥락이 PRD v0.2.pdf",
        excerpt: "답변은 근거가 부족하면 생성하지 않는다. 인용한 원문 위치를 항상 함께 제시한다.",
      },
    ],
  },
  {
    match: /범위|scope|poc/i,
    text: "PoC 범위는 회의 녹음과 문서 업로드 두 갈래로 한정했습니다[1]. 슬랙 연동은 이번 범위에서 제외했습니다[1].",
    sources: [
      {
        index: 1,
        sourceId: "src-kickoff",
        chunkId: "src-kickoff#1",
        kind: "meeting",
        title: "9/8 제품 킥오프 회의",
        excerpt:
          "PoC 범위는 회의 녹음과 문서 업로드 두 갈래로 갑니다. 슬랙 연동은 이번 범위에서 뺍니다.",
      },
    ],
  },
  {
    match: /키|byok|api key/i,
    text: "LLM은 BYOK 방식으로 사용자가 키를 등록합니다[1]. 키는 서버에서 암호화해 저장하고 어떤 응답으로도 원문을 돌려주지 않습니다[1].",
    sources: [
      {
        index: 1,
        sourceId: "src-tech-review",
        chunkId: "src-tech-review#1",
        kind: "meeting",
        title: "9/11 기술 검토 회의",
        excerpt:
          "LLM은 BYOK로 받습니다. 키는 서버에서 암호화해 저장하고 응답으로는 절대 돌려주지 않습니다.",
      },
    ],
  },
];

export const fallbackAnswer = {
  text: "이 워크스페이스의 소스에서는 질문에 답할 근거를 찾지 못했습니다. 관련 회의나 문서를 먼저 올려주세요.",
  sources: [] as AnswerSource[],
};

/**
 * 소스 종류별 처리 단계 시퀀스.
 *
 * 회의 녹음만 STT(`transcribing`)를 거칩니다. mock은 이 순서대로
 * 진행률을 나눠 단계를 넘깁니다.
 */
export const stageSequence: Record<SourceKind, ProcessingStage[]> = {
  document: ["uploaded", "analyzing", "graphing", "completed"],
  meeting: ["uploaded", "transcribing", "analyzing", "graphing", "completed"],
};
