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

export type LlmProvider = "anthropic" | "openai";

export type CreateWorkspaceInput = {
  name: string;
  /** BYOK. 서버는 암호화해 저장하고 어떤 응답으로도 다시 내려주지 않습니다. */
  llmApiKey: string;
  llmProvider: LlmProvider;
};

/** 키 유효성 검증 결과. 실제 호출로 확인하므로 형식만 맞아도 실패할 수 있습니다. */
export type ApiKeyValidation = {
  valid: boolean;
  /** 사용자에게 그대로 보여줄 결과 문구 */
  message: string;
};

/**
 * 워크스페이스에 저장된 BYOK 키 정보.
 *
 * 키 원문은 포함되지 않습니다. 사용자가 어떤 키를 넣었는지 알아볼 수 있도록
 * 마지막 4자만 `keyHint`로 내려줍니다.
 */
export type WorkspaceSecrets = {
  provider: LlmProvider;
  keyHint: string;
  updatedAt: string;
};

export type Source = {
  id: string;
  workspaceId: string;
  kind: SourceKind;
  title: string;
  status: ProcessingStatus;
  createdAt: string;
  /** 문서일 때만 */
  sizeBytes?: number;
  /** 회의 녹음일 때만 */
  durationSeconds?: number;
};

/** 원문 뷰어가 쓰는 정규화된 본문 */
export type SourceContent = {
  sourceId: string;
  title: string;
  kind: SourceKind;
  /** 청크 단위 본문. 근거 하이라이트가 chunkId로 위치를 찾습니다. */
  chunks: { id: string; text: string }[];
};

/**
 * 처리 파이프라인의 단계.
 *
 * 회의 녹음은 `transcribing`을 거치고 문서는 건너뜁니다. 표시 문구는
 * 프론트가 소유하므로 서버는 이 키만 내려줍니다.
 */
export type ProcessingStage = "uploaded" | "transcribing" | "analyzing" | "graphing" | "completed";

/** 업로드 직후의 비동기 처리 상태 */
export type ProcessingJob = {
  id: string;
  sourceId: string;
  /** 어떤 단계를 거치는지 화면이 판단할 수 있게 소스 종류를 함께 내려줍니다. */
  sourceKind: SourceKind;
  status: ProcessingStatus;
  /** 0..1 */
  progress: number;
  stage: ProcessingStage;
  errorMessage?: string;
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
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  type: RelationType;
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
  chunkId: string;
  kind: SourceKind;
  title: string;
  excerpt: string;
};

/**
 * Ask 스트리밍 이벤트.
 *
 * `sources`가 먼저 오고 `token`이 이어지며 `done`으로 끝납니다.
 * 근거를 찾지 못하면 `token` 없이 `error`로 끝낼 수 있습니다.
 */
export type AnswerEvent =
  | { type: "sources"; sources: AnswerSource[] }
  | { type: "token"; text: string }
  | { type: "done" }
  | { type: "error"; message: string };
