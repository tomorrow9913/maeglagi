/**
 * 화면이 사용하는 API DTO입니다.
 *
 * 백엔드가 `/openapi.json`을 내보내면 `openapi-typescript`로 생성한 타입이
 * 기준이 되고, 이 파일은 생성 타입의 별칭만 남깁니다. 그때까지는 Day 1에
 * 합의한 API 명세를 여기에 손으로 유지합니다.
 */

import type { ContextKind, ProcessingStatus, SourceKind } from "@/types/context";

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

export type CreateWorkspaceInput = {
  name: string;
  /** BYOK. 서버는 암호화해 저장하고 다시 내려주지 않습니다. */
  llmApiKey: string;
  llmProvider: "anthropic" | "openai";
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

/** 업로드 직후의 비동기 처리 상태 */
export type ProcessingJob = {
  id: string;
  sourceId: string;
  status: ProcessingStatus;
  /** 0..1 */
  progress: number;
  /** 사용자에게 보여줄 현재 단계 */
  stage: string;
  errorMessage?: string;
};

export type ContextItem = {
  id: string;
  kind: ContextKind;
  title: string;
  summary: string;
  occurredAt: string;
  sourceIds: string[];
  /** Temporal 규칙: 이후 결정으로 대체되면 대체한 항목의 id */
  supersededBy?: string;
};

export type ContextTimelineQuery = {
  kinds?: ContextKind[];
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
