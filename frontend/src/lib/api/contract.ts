import type { UploadOptions } from "./client";
import type {
  AnswerEvent,
  ContextItem,
  ContextTimelineQuery,
  CreateWorkspaceInput,
  KnowledgeGraph,
  ProcessingJob,
  Source,
  SourceContent,
  Workspace,
} from "./types";

/**
 * 화면이 의존하는 단 하나의 API 표면입니다.
 *
 * 실 구현(`http/`)과 mock 구현(`mock/`)이 이 인터페이스를 똑같이 만족하므로
 * 화면 코드는 어느 쪽이 연결됐는지 알 필요가 없습니다. 새 엔드포인트를
 * 추가할 때는 여기 → 실 구현 → mock 구현 순서로 넓힙니다.
 */
export interface MaeglagiApi {
  listWorkspaces(signal?: AbortSignal): Promise<Workspace[]>;
  getWorkspace(workspaceId: string, signal?: AbortSignal): Promise<Workspace>;
  createWorkspace(input: CreateWorkspaceInput, signal?: AbortSignal): Promise<Workspace>;

  listSources(workspaceId: string, signal?: AbortSignal): Promise<Source[]>;
  getSourceContent(sourceId: string, signal?: AbortSignal): Promise<SourceContent>;
  /** 문서 업로드. 전송이 끝나면 반환된 job으로 처리 진행률을 폴링합니다. */
  uploadDocument(workspaceId: string, file: File, options?: UploadOptions): Promise<ProcessingJob>;
  /** 회의 녹음 업로드. STT 이후 파이프라인은 문서와 동일합니다. */
  uploadRecording(
    workspaceId: string,
    audio: Blob,
    options?: UploadOptions,
  ): Promise<ProcessingJob>;
  getJob(jobId: string, signal?: AbortSignal): Promise<ProcessingJob>;

  listContextItems(
    workspaceId: string,
    query?: ContextTimelineQuery,
    signal?: AbortSignal,
  ): Promise<ContextItem[]>;
  getKnowledgeGraph(workspaceId: string, signal?: AbortSignal): Promise<KnowledgeGraph>;

  /**
   * 질문에 대한 답을 스트리밍합니다.
   *
   * 호출부는 `for await`로 소비하고, 중단은 `signal`로 합니다.
   */
  ask(workspaceId: string, question: string, signal?: AbortSignal): AsyncIterable<AnswerEvent>;
}
