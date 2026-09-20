/**
 * 화면이 사용하는 API DTO입니다.
 *
 * 백엔드가 `/openapi.json`을 내보내면 `openapi-typescript`로 생성한 타입이
 * 기준이 되고, 이 파일은 생성 타입의 별칭만 남깁니다. 그때까지는 Day 1에
 * 합의한 API 명세를 여기에 손으로 유지합니다.
 */

import type { ContextKind, ProcessingStatus, SourceKind } from "@/types/context";

// API 소비자가 도메인 타입까지 한 곳에서 가져올 수 있게 다시 내보냅니다.
export type { ContextKind, ProcessingStatus, SourceKind };

/** Ontology entity 종류. Graph 노드 색(chart-1..5)과 순서를 맞춥니다. */
export type EntityType = "person" | "project" | "decision" | "task" | "event";

export type RelationType =
  "participates_in" | "decided" | "assigned_to" | "blocks" | "relates_to" | "supersedes";

export type Workspace = {
  id: string;
  name: string;
  createdAt: string;
  sourceCount: number;
};

/** Account-wide MCP access token metadata. The secret appears only in create's response. */
export type McpToken = {
  id: string;
  label: string;
  tokenHint: string;
  createdAt: string;
  lastUsedAt: string | null;
  expiresAt: string | null;
};

export type McpTokenList = { items: McpToken[] };
export type CreatedMcpToken = { item: McpToken; token: string };

/** 백엔드 provider registry가 소유하는 동적 provider 식별자입니다. */
export type LlmProvider = string;

/** workspace에서 사용할 수 있는 AI provider catalog 항목입니다. */
export type AiProvider = {
  id: LlmProvider;
  displayName: string;
  authMode?: "apiKey" | "optionalApiKey" | "none";
  requiresBaseUrl?: boolean;
  capabilities: string[];
  configured: boolean;
  models: string[];
  /**
   * 이 공급자가 용도마다 미리 골라 두는 모델. 키를 넣기 전에도 공급자를 고르는 즉시 보여줄 수
   * 있습니다. 기본 모델이 없는 용도(예: 임베딩이 없는 공급자)는 비어 있습니다.
   */
  defaultModels?: Partial<Record<ModelRole, string>>;
};

/** 모델이 쓰이는 용도. 서버가 내려주는 순서와 같습니다. */
export type ModelRole = "answer" | "extraction" | "embedding" | "transcription";

/** 어느 공급자의 어느 모델인지. 한 워크스페이스가 용도마다 다른 공급자를 쓸 수도 있습니다. */
export type ModelOption = { provider: LlmProvider; model: string; credentialId?: string | null };

/** 한 용도에서 고를 수 있는 모델과 지금 선택된 모델. */
export type RoleModels = {
  role: ModelRole;
  /** 이 키로 쓸 수 있는 모델. 서버가 추천 순으로 정렬해 주므로 첫 번째를 미리 선택합니다. */
  options: ModelOption[];
  /** 워크스페이스에 저장된 선택. 키만 넣은 단계(워크스페이스 생성 전)에는 null입니다. */
  selected: ModelOption | null;
  /**
   * 바꿀 수 없는 상태. 임베딩만 해당하며, 워크스페이스를 만들 때 정한 뒤로는 잠깁니다(모델마다
   * 벡터가 달라 섞어 검색할 수 없습니다). LLM 모델은 항상 바꿀 수 있습니다.
   */
  locked: boolean;
};

export type WorkspaceModels = { roles: RoleModels[] };

/** 용도별로 고른 모델. 고르지 않은 용도는 비워 둡니다. */
export type ModelSelections = Partial<Record<ModelRole, ModelOption>>;

export type CreateWorkspaceInput = {
  name: string;
  /** 기존 인라인 등록 경로. 저장된 계정 연결을 고를 때는 보내지 않습니다. */
  llmApiKey?: string;
  llmProvider?: LlmProvider;
  llmBaseUrl?: string;
  credentialId?: string;
  /** 용도별로 고른 모델. 비우면 서버가 정한 기본을 씁니다. */
  models?: ModelSelections;
};

/** 키 유효성 검증 결과. 실제 호출로 확인하므로 형식만 맞아도 실패할 수 있습니다. */
export type ApiKeyValidation = {
  valid: boolean;
  /** 사용자에게 그대로 보여줄 결과 문구 */
  message: string;
  /**
   * 실패 이유 코드. 서버가 내려줄 때만 있습니다(현재 백엔드는 보내지 않습니다).
   * Ollama: "invalid_url" | "address_not_permitted" | "https_required" | "unreachable"
   */
  reason?: string;
};

/**
 * 계정에 저장된 AI 연결 정보.
 *
 * 키 원문은 포함되지 않습니다. 사용자가 어떤 키를 넣었는지 알아볼 수 있도록
 * 마지막 4자만 `keyHint`로 내려줍니다.
 */
export type WorkspaceSecrets = {
  id: string;
  provider: LlmProvider;
  label: string;
  keyHint: string;
  baseUrl?: string | null;
  status: string;
  isDefault: boolean;
  updatedAt: string;
};

export type Source = {
  id: string;
  workspaceId: string;
  kind: SourceKind;
  title: string;
  status: ProcessingStatus;
  analysisMode?: "server" | "agent";
  createdAt: string;
  /** 문서일 때만 */
  sizeBytes?: number;
  /** 회의 녹음일 때만 */
  durationSeconds?: number;
  /** server는 오디오 STT, browser는 브라우저 받아쓰기 원문입니다. */
  transcriptSource?: "server" | "browser" | "agent";
  projectId?: string | null;
  projectIds?: string[];
  associations?: SourceAssociation[];
  associationRevision?: number;
  hasRecording?: boolean;
};

export type SourceAssociation = { personId: string; role: "participant" | "author" };
export type SourceAssociations = { revision: number; projectIds: string[]; people: SourceAssociation[] };

/** 원문 뷰어가 쓰는 정규화된 본문 */
export type SourceContent = {
  sourceId: string;
  title: string;
  kind: SourceKind;
  hasRecording?: boolean;
  /** 저장된 원문. 검토 중인 수정본과 확인된 대본은 인덱싱 전에도 제공됩니다. */
  originalText: string | null;
  /** 회의 원문의 발언. 청크 ID와 무관하며 원본 녹음의 시각을 보존합니다. */
  utterances: MeetingUtterance[];
  /** 청크 단위 본문. 근거 하이라이트가 chunkId로 위치를 찾습니다. */
  chunks: {
    id: string;
    text: string;
    /** 회의 녹음에서 이 구간이 시작·끝나는 시각(초). 문서에는 없습니다. */
    startSeconds?: number | null;
    endSeconds?: number | null;
  }[];
};

/**
 * 처리 파이프라인의 단계.
 *
 * 회의 녹음은 `transcribing`을 거치고 문서는 건너뜁니다. 표시 문구는
 * 프론트가 소유하므로 서버는 이 키만 내려줍니다.
 */
export type ProcessingStage = "uploaded" | "transcribing" | "awaiting_review" | "confirmed" | "awaiting_agent" | "analyzing" | "graphing" | "completed";

/** 업로드 직후의 비동기 처리 상태 */
export type ProcessingJob = {
  id: string;
  sourceId: string;
  /** 어떤 단계를 거치는지 화면이 판단할 수 있게 소스 종류를 함께 내려줍니다. */
  sourceKind: SourceKind;
  transcriptSource?: "server" | "browser" | "agent";
  analysisMode?: "server" | "agent";
  status: ProcessingStatus;
  /** 0..1 */
  progress: number;
  stage: ProcessingStage;
  errorMessage?: string;
};

export type TranscriptSourceInput = {
  text: string;
  title?: string;
  durationSeconds?: number;
  utterances?: MeetingUtterance[];
  projectId?: string | null;
  projectIds?: string[];
};

export type WorkspacePerson = {
  id: string;
  workspaceId: string;
  name: string;
  email?: string | null;
  aliases: string[];
  role?: string | null;
  archivedAt: string | null;
  createdAt: string;
  updatedAt: string;
};

export type PersonInput = { name: string; email?: string | null; aliases?: string[]; role?: string | null };
export type WorkspaceProject = {
  id: string;
  workspaceId: string;
  name: string;
  goal: string | null;
  description: string | null;
  ownerPersonId: string | null;
  participantIds?: string[];
  revision?: number;
  startsOn: string | null;
  endsOn: string | null;
  archivedAt: string | null;
  createdAt: string;
  updatedAt: string;
};
export type ProjectInput = {
  name: string;
  goal?: string | null;
  description?: string | null;
  ownerPersonId?: string | null;
  participantIds?: string[];
  startsOn?: string | null;
  endsOn?: string | null;
};
export type MeetingUtterance = {
  id: string;
  personId?: string | null;
  speakerName: string;
  text: string;
  startSeconds?: number | null;
  endSeconds?: number | null;
};
export type MeetingReview = {
  sourceId: string;
  title: string;
  transcriptSource: "server" | "browser" | "agent";
  analysisMode?: "server" | "agent";
  reviewState: "transcribing" | "awaiting_review" | "awaiting_agent" | "confirmed";
  status: ProcessingStatus;
  stage: ProcessingStage;
  errorMessage: string | null;
  revision: number;
  projectId: string | null;
  projectIds?: string[];
  suggestedParticipants?: WorkspacePerson[];
  utterances: MeetingUtterance[];
  rawTranscriptText: string | null;
  rawUtterances: MeetingUtterance[];
  confirmedAt: string | null;
  confirmedSnapshot: unknown | null;
};

/** 맥락 항목이 어떤 소스에서 나왔는지. 카드에서 바로 보여줄 수 있게 함께 내려줍니다. */
export type ContextItemSource = {
  id: string;
  kind: SourceKind;
  title: string;
  /** 근거가 된 청크. 원문 뷰어가 이 위치로 이동합니다. */
  chunkId?: string;
};

export type ContextItem = {
  id: string;
  kind: ContextKind;
  title: string;
  summary: string;
  occurredAt: string;
  sources: ContextItemSource[];
  /** Temporal 규칙: 이후 결정으로 대체되면 대체한 항목의 id */
  supersededBy?: string;
};

/** Context Store의 한 항목. 근거가 된 원문 인용을 함께 가집니다. */
export type ContextStoreItem = {
  title: string;
  description: string;
  /** 이 항목을 뒷받침하는 원문 문장 */
  sourceRefs: string[];
  sourceId: string | null;
  /** 결정일 (결정에만 있습니다) */
  decidedAt: string | null;
  /** 담당자와 기한 (할 일에만 있습니다) */
  assignee: string | null;
  dueAt: string | null;
};

/**
 * 프로젝트의 현재 상황. Graph가 업무 세계의 구조라면 Context Store는 지금의 상태를 담당합니다.
 * 새 소스가 분석될 때마다 갱신되고, 대체된 결정과 해결된 이슈는 여기서 빠집니다.
 */
export type ContextStore = {
  subject: string;
  summary: string;
  currentState: string;
  openIssues: ContextStoreItem[];
  /** 아직 유효한 결정만 담습니다. 대체된 결정은 타임라인에서 볼 수 있습니다. */
  decisions: ContextStoreItem[];
  nextActions: ContextStoreItem[];
  sourceIds: string[];
  updatedAt: string;
};

export type ContextTimelineQuery = {
  kinds?: ContextKind[];
  /** 근거 소스의 종류로 거릅니다. 비우면 전체입니다. */
  sourceKinds?: SourceKind[];
  /** ISO-8601 (inclusive) */
  from?: string;
  to?: string;
};

export type GraphNode = {
  id: string;
  type: EntityType;
  label: string;
  /** 연결 수. 노드 크기를 정할 때 씁니다. */
  degree: number;
  /** 이 엔티티가 등장한 근거 소스. 상세 패널에서 원문으로 이동합니다. */
  sources: ContextItemSource[];
  /** 온톨로지의 정확한 종류(Meeting, Issue 등). `type`은 화면이 그리는 다섯 종류로 줄인 값입니다. */
  kind?: string;
  /** 이후 결정이 이 결정을 명시적으로 대체했다면 대체한 결정의 id */
  supersededBy?: string | null;
  material?: boolean;
  sourceId?: string | null;
  directoryId?: string | null;
  directoryKind?: "Person" | "Project" | null;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  type: RelationType;
  /** 온톨로지의 정확한 관계(WORKS_ON 등) */
  kind?: string;
  /** 관계의 유효 기간. 비어 있으면 시작을 모르거나 종료가 확인되지 않은 관계입니다. */
  validFrom?: string | null;
  validTo?: string | null;
  explicit?: boolean;
  role?: "participant" | "author" | "project" | null;
};

/** 그래프를 볼 기준 시점. 비우면 지금 유효한 관계만 보여줍니다. */
export type KnowledgeGraphQuery = {
  /** ISO-8601 날짜 또는 시각. 이 시점에 유효했던 관계만 돌려줍니다. */
  at?: string;
  includeMaterials?: boolean;
};

export type KnowledgeGraph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

/** 답변이 인용한 근거 한 건 */
export type AnswerSource = {
  /** 답변 본문의 [n]과 대응 */
  index: number;
  sourceId: string;
  /** 본문 검색 근거는 색인 청크 없이 소스 자체를 인용할 수 있습니다. */
  chunkId?: string;
  kind: SourceKind;
  title: string;
  excerpt: string;
  /** 회의 근거가 시작되는 시각(초). 원문 뷰어가 이 위치로 이동합니다. 문서 근거에는 없습니다. */
  timestamp?: number;
};

/**
 * Ask 스트리밍 이벤트.
 *
 * `sources`가 먼저 오고 `token`이 이어지며 `done`으로 끝납니다.
 * 근거를 찾지 못하면 `token` 없이 `error`로 끝낼 수 있습니다. 이때는 실패가 아니라 정상
 * 결과이므로 `code: "no_evidence"`가 붙습니다. `code`가 없는 `error`는 실패입니다.
 */
export type AnswerEvent =
  | { type: "sources"; sources: AnswerSource[] }
  | { type: "token"; text: string }
  | { type: "done" }
  | { type: "error"; message: string; code?: "no_evidence" };
