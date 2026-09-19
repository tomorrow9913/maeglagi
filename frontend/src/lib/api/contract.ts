import type { UploadOptions } from "./client";
import type {
  AnswerEvent,
  AiProvider,
  ApiKeyValidation,
  ContextItem,
  ContextTimelineQuery,
  CreateWorkspaceInput,
  KnowledgeGraph,
  ProcessingJob,
  LlmProvider,
  Source,
  SourceContent,
  TranscriptSourceInput,
  Workspace,
  WorkspaceSecrets,
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
  /**
   * 서버가 지원하는 provider 목록. workspace가 아직 없는 최초 생성 화면에서 씁니다.
   * `configured`와 `models`는 workspace마다 다른 값이라 항상 비어 있습니다.
   */
  listProviders(signal?: AbortSignal): Promise<AiProvider[]>;
  /** 백엔드 registry 기준으로 workspace에서 사용할 수 있는 provider를 조회합니다. */
  listWorkspaceProviders(workspaceId: string, signal?: AbortSignal): Promise<AiProvider[]>;

  /**
   * BYOK 키가 실제로 쓸 수 있는 키인지 확인합니다.
   *
   * 서버가 provider에 가벼운 호출을 한 번 보내 확인하며, 키를 저장하지
   * 않습니다. 저장은 createWorkspace나 updateApiKey가 합니다.
   */
  validateApiKey(
    input: { provider: LlmProvider; apiKey: string },
    signal?: AbortSignal,
  ): Promise<ApiKeyValidation>;
  /** 저장된 키의 provider와 마지막 4자. 키를 등록하지 않았으면 null입니다. */
  getWorkspaceSecrets(workspaceId: string, signal?: AbortSignal): Promise<WorkspaceSecrets | null>;
  /** 키 교체. 기존 키는 덮어씌워지고 복구할 수 없습니다. */
  updateApiKey(
    workspaceId: string,
    input: { provider: LlmProvider; apiKey: string },
    signal?: AbortSignal,
  ): Promise<WorkspaceSecrets>;

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
  /** 브라우저 받아쓰기 대본. 서버 STT 단계 없이 공통 분석 파이프라인으로 들어갑니다. */
  uploadTranscript(
    workspaceId: string,
    input: TranscriptSourceInput,
    signal?: AbortSignal,
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
