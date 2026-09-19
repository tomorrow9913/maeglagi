import type {
  AnswerSource,
  ProcessingStage,
  ContextItem,
  ContextStore,
  KnowledgeGraph,
  ModelRole,
  Source,
  SourceContent,
  SourceKind,
  Workspace,
} from "../types";

export const DEMO_WORKSPACE_ID = "demo";

export const workspaces: Workspace[] = [
  {
    id: DEMO_WORKSPACE_ID,
    name: "맥락이 PoC",
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
    originalText: null,
    utterances: [],
    chunks: [
      {
        id: "src-kickoff#1",
        text: "정민규: PoC 범위는 회의 녹음과 문서 업로드 두 갈래로 갑니다. 슬랙 연동은 이번 범위에서 뺍니다.",
        startSeconds: 0,
        endSeconds: 38,
      },
      {
        id: "src-kickoff#2",
        text: "윤희원: 그러면 프론트는 Timeline, Graph, Ask 세 화면에 집중하겠습니다. 소스 업로드는 문서 먼저 붙이고 녹음을 이어서 붙입니다.",
        startSeconds: 38,
        endSeconds: 81,
      },
      {
        id: "src-kickoff#3",
        text: "정민규: 저장소는 PostgreSQL, MinIO, pgvector, Neo4j 네 가지로 확정합니다. 이건 Day 1에 세워둡니다.",
        startSeconds: 81,
        endSeconds: 120,
      },
    ],
  },
  {
    sourceId: "src-prd",
    title: "맥락이 PRD v0.2.pdf",
    kind: "document",
    originalText: null,
    utterances: [],
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
    originalText: null,
    utterances: [],
    chunks: [
      {
        id: "src-tech-review#1",
        text: "정민규: LLM은 BYOK로 받습니다. 키는 서버에서 암호화해 저장하고 응답으로는 절대 돌려주지 않습니다.",
        startSeconds: 0,
        endSeconds: 44,
      },
      {
        id: "src-tech-review#2",
        text: "윤희원: 검색은 벡터 단독으로는 근거가 약해서, 그래프 탐색을 붙인 hybrid retrieval로 갑니다.",
        startSeconds: 44,
        endSeconds: 97,
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
    sources: [
      {
        id: "src-kickoff",
        kind: "meeting",
        title: "9/8 제품 킥오프 회의",
        chunkId: "src-kickoff#1",
      },
    ],
  },
  {
    id: "ctx-2",
    kind: "decision",
    title: "저장소를 PostgreSQL·MinIO·pgvector·Neo4j 4종으로 확정",
    summary: "원문, 메타데이터, 임베딩, 그래프를 각각의 저장소가 맡습니다.",
    occurredAt: "2026-09-08T10:55:00Z",
    sources: [
      {
        id: "src-kickoff",
        kind: "meeting",
        title: "9/8 제품 킥오프 회의",
        chunkId: "src-kickoff#3",
      },
    ],
  },
  {
    id: "ctx-3",
    kind: "issue",
    title: "벡터 검색만으로는 근거가 약함",
    summary: "질문이 여러 회의에 걸치면 관련 청크를 놓치는 사례가 나왔습니다.",
    occurredAt: "2026-09-11T06:20:00Z",
    sources: [
      {
        id: "src-tech-review",
        kind: "meeting",
        title: "9/11 기술 검토 회의",
        chunkId: "src-tech-review#2",
      },
    ],
    supersededBy: "ctx-4",
  },
  {
    id: "ctx-4",
    kind: "decision",
    title: "Hybrid retrieval(벡터 + 그래프) 채택",
    summary: "벡터 검색 결과를 그래프 이웃으로 확장해 근거 후보를 넓힙니다.",
    occurredAt: "2026-09-11T06:35:00Z",
    sources: [
      {
        id: "src-tech-review",
        kind: "meeting",
        title: "9/11 기술 검토 회의",
        chunkId: "src-tech-review#2",
      },
    ],
  },
  {
    id: "ctx-5",
    kind: "task",
    title: "BYOK 키 암호화 저장 구현",
    summary: "키는 저장 시 암호화하고 어떤 응답으로도 원문을 내보내지 않습니다.",
    occurredAt: "2026-09-11T06:48:00Z",
    sources: [
      {
        id: "src-tech-review",
        kind: "meeting",
        title: "9/11 기술 검토 회의",
        chunkId: "src-tech-review#1",
      },
    ],
  },
  {
    id: "ctx-6",
    kind: "event",
    title: "PRD v0.2 공유",
    summary: "제품 정의와 답변 원칙을 문서로 정리해 공유했습니다.",
    occurredAt: "2026-09-09T02:10:00Z",
    sources: [
      { id: "src-prd", kind: "document", title: "맥락이 PRD v0.2.pdf", chunkId: "src-prd#1" },
    ],
  },
];

export const knowledgeGraph: KnowledgeGraph = {
  nodes: [
    {
      id: "person-minkyu",
      type: "person",
      label: "정민규",
      degree: 4,
      sources: [
        {
          id: "src-kickoff",
          kind: "meeting",
          title: "9/8 제품 킥오프 회의",
          chunkId: "src-kickoff#1",
        },
      ],
    },
    {
      id: "person-heewon",
      type: "person",
      label: "윤희원",
      degree: 4,
      sources: [
        {
          id: "src-tech-review",
          kind: "meeting",
          title: "9/11 기술 검토 회의",
          chunkId: "src-tech-review#2",
        },
      ],
    },
    {
      id: "project-maeglagi",
      type: "project",
      label: "맥락이 PoC",
      degree: 5,
      sources: [
        { id: "src-prd", kind: "document", title: "맥락이 PRD v0.2.pdf", chunkId: "src-prd#1" },
      ],
    },
    {
      id: "decision-scope",
      type: "decision",
      label: "PoC 범위 한정",
      degree: 2,
      sources: [
        {
          id: "src-kickoff",
          kind: "meeting",
          title: "9/8 제품 킥오프 회의",
          chunkId: "src-kickoff#1",
        },
      ],
    },
    {
      id: "decision-hybrid",
      type: "decision",
      label: "Hybrid retrieval 채택",
      degree: 3,
      sources: [
        {
          id: "src-tech-review",
          kind: "meeting",
          title: "9/11 기술 검토 회의",
          chunkId: "src-tech-review#2",
        },
      ],
    },
    {
      id: "task-byok",
      type: "task",
      label: "BYOK 키 암호화",
      degree: 2,
      sources: [
        {
          id: "src-tech-review",
          kind: "meeting",
          title: "9/11 기술 검토 회의",
          chunkId: "src-tech-review#1",
        },
      ],
    },
    {
      id: "event-kickoff",
      type: "event",
      label: "9/8 킥오프",
      degree: 3,
      sources: [
        {
          id: "src-kickoff",
          kind: "meeting",
          title: "9/8 제품 킥오프 회의",
          chunkId: "src-kickoff#3",
        },
      ],
    },
  ],
  edges: [
    {
      id: "e1",
      source: "person-minkyu",
      target: "event-kickoff",
      type: "participates_in",
      validFrom: "2026-09-08",
    },
    {
      id: "e2",
      source: "person-heewon",
      target: "event-kickoff",
      type: "participates_in",
      validFrom: "2026-09-08",
    },
    {
      id: "e3",
      source: "person-minkyu",
      target: "decision-scope",
      type: "decided",
      validFrom: "2026-09-08",
    },
    {
      id: "e4",
      source: "decision-scope",
      target: "project-maeglagi",
      type: "relates_to",
      validFrom: "2026-09-08",
      validTo: "2026-09-10",
    },
    {
      id: "e5",
      source: "person-heewon",
      target: "decision-hybrid",
      type: "decided",
      validFrom: "2026-09-11",
    },
    {
      id: "e6",
      source: "decision-hybrid",
      target: "project-maeglagi",
      type: "relates_to",
      validFrom: "2026-09-11",
    },
    {
      id: "e7",
      source: "task-byok",
      target: "person-minkyu",
      type: "assigned_to",
      validFrom: "2026-09-11",
    },
    {
      id: "e8",
      source: "task-byok",
      target: "project-maeglagi",
      type: "relates_to",
      validFrom: "2026-09-11",
    },
    {
      id: "e9",
      source: "decision-hybrid",
      target: "decision-scope",
      type: "supersedes",
      validFrom: "2026-09-11",
    },
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
    match: /저장소|postgres|pgvector|neo4j|minio/i,
    text: "저장소는 PostgreSQL, MinIO, pgvector, Neo4j 네 가지로 확정했습니다[1]. 원문·메타데이터·임베딩·그래프를 각 저장소가 나눠 맡고, Day 1에 먼저 세워두기로 했습니다[1].",
    sources: [
      {
        index: 1,
        sourceId: "src-kickoff",
        chunkId: "src-kickoff#3",
        kind: "meeting",
        title: "9/8 제품 킥오프 회의",
        excerpt:
          "저장소는 PostgreSQL, MinIO, pgvector, Neo4j 네 가지로 확정합니다. 이건 Day 1에 세워둡니다.",
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
  text: "이 워크스페이스의 소스에서는 답할 근거를 찾지 못했어요. 관련 회의나 문서를 먼저 올려주세요.",
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

/** 위 타임라인을 바탕으로 한 현재 상황. 대체된 결정과 해결된 이슈는 빠져 있습니다. */
export const contextStore: ContextStore = {
  subject: "맥락이 PoC",
  summary:
    "회의 녹음과 문서 업로드에서 결정·이슈·이벤트를 뽑아 Timeline과 Graph로 보여주는 PoC입니다.",
  currentState:
    "검색은 벡터에 그래프 이웃을 더한 Hybrid retrieval로 가기로 했고, 저장소 4종 구성은 확정됐습니다. 슬랙·지라 연동은 이번 PoC 범위에서 빠졌습니다.",
  openIssues: [
    {
      title: "그래프 노드가 늘면 화면이 복잡해짐",
      description: "노드가 스무 개를 넘으면 라벨이 겹쳐 읽기 어렵습니다.",
      sourceRefs: ["노드가 많아지면 라벨이 서로 겹친다"],
      sourceId: "src-tech-review",
      decidedAt: null,
      assignee: null,
      dueAt: null,
    },
  ],
  decisions: [
    {
      title: "Hybrid retrieval(벡터 + 그래프) 채택",
      description: "벡터 검색 결과를 그래프 이웃으로 확장해 근거 후보를 넓힙니다.",
      sourceRefs: ["벡터 검색만으로는 부족하니 그래프 이웃까지 넓히자"],
      sourceId: "src-tech-review",
      decidedAt: "2026-09-11",
      assignee: null,
      dueAt: null,
    },
    {
      title: "PoC 범위를 회의 녹음과 문서 업로드로 한정",
      description: "슬랙·지라 연동은 이번 PoC에서 제외합니다.",
      sourceRefs: ["슬랙과 지라 연동은 이번에는 빼기로 했습니다"],
      sourceId: "src-kickoff",
      decidedAt: "2026-09-08",
      assignee: null,
      dueAt: null,
    },
  ],
  nextActions: [
    {
      title: "Timeline 화면에 대체 관계 표시",
      description: "",
      sourceRefs: ["대체된 결정은 흐리게 보여주기로"],
      sourceId: "src-tech-review",
      decidedAt: null,
      assignee: "윤희원",
      dueAt: "2026-09-17",
    },
  ],
  sourceIds: ["src-kickoff", "src-tech-review"],
  updatedAt: "2026-09-11T07:10:00Z",
};

/**
 * provider가 키로 내려주는 모델을 용도별로 나눈 mock 목록입니다.
 *
 * 실제로는 서버가 공급자의 모델 목록을 받아 분류합니다. Anthropic과 NVIDIA에는
 * 임베딩·받아쓰기 모델이 없어, 옵션이 빈 용도를 화면에서 확인할 수 있습니다.
 */
export const modelCatalog: Record<string, Partial<Record<ModelRole, string[]>>> = {
  ollama: {
    answer: ["llama3.2:latest", "qwen2.5:latest"],
    extraction: ["llama3.2:latest", "qwen2.5:latest"],
    embedding: ["nomic-embed-text:latest"],
  },
  openai: {
    answer: ["gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini"],
    extraction: ["gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini"],
    embedding: ["text-embedding-3-small", "text-embedding-3-large"],
    transcription: ["whisper-1", "gpt-4o-transcribe"],
  },
  anthropic: {
    answer: ["claude-haiku-4-5", "claude-sonnet-4-20250514"],
    extraction: ["claude-haiku-4-5", "claude-sonnet-4-20250514"],
  },
  nvidia: {
    answer: ["meta/llama-3.1-8b-instruct", "meta/llama-3.1-70b-instruct"],
    extraction: ["meta/llama-3.1-8b-instruct", "meta/llama-3.1-70b-instruct"],
  },
};
