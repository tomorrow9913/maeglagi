import { ApiError, type UploadOptions } from "../client";
import { MOCK_LATENCY_MS } from "../config";
import type { MaeglagiApi } from "../contract";
import type {
  AnswerEvent,
  AiProvider,
  ApiKeyValidation,
  ContextItem,
  LlmProvider,
  ModelRole,
  ModelSelections,
  ProcessingJob,
  MeetingReview,
  McpToken,
  WorkspacePerson,
  WorkspaceProject,
  Source,
  SourceContent,
  Workspace,
  WorkspaceModels,
  WorkspaceSecrets,
} from "../types";
import { BOOTSTRAP_AI_PROVIDERS } from "../providers";
import {
  answers,
  contextItems,
  contextStore,
  fallbackAnswer,
  knowledgeGraph,
  modelCatalog,
  stageSequence,
  sourceContents,
  sources as seedSources,
  workspaces as seedWorkspaces,
} from "./fixtures";

/** 처리에 걸리는 것처럼 보일 시간. 폴링 UI를 확인하기에 충분한 길이입니다. */
const JOB_DURATION_MS = 12_000;

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }

    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true },
    );
  });
}

/**
 * mock 상태는 모듈 스코프에 둡니다.
 *
 * 새로고침하면 초기 fixture로 돌아갑니다. 업로드한 소스가 처리되는 과정을
 * 화면에서 확인할 수 있을 만큼만 상태를 들고 있습니다.
 */
const state = {
  workspaces: seedWorkspaces.map((workspace) => ({ ...workspace })),
  sources: seedSources.map((source) => ({
    ...source,
    projectIds: ["project-maeglagi"],
    associations: source.kind === "meeting" ? [{ personId: "person-minkyu", role: "participant" as const }, { personId: "person-heewon", role: "participant" as const }] : [{ personId: "person-minkyu", role: "author" as const }],
    associationRevision: 0,
    hasRecording: false,
  })) as Source[],
  recordings: new Map<string, Blob>(),
  jobs: new Map<string, ProcessingJob & { startedAt: number }>(),
  people: [
    { id: "person-minkyu", workspaceId: "demo", name: "정민규", email: "minkyu@example.com", aliases: [], role: "기획", archivedAt: null, createdAt: "2026-09-08T09:00:00Z", updatedAt: "2026-09-08T09:00:00Z" },
    { id: "person-heewon", workspaceId: "demo", name: "윤희원", email: "heewon@example.com", aliases: [], role: "개발", archivedAt: null, createdAt: "2026-09-08T09:00:00Z", updatedAt: "2026-09-08T09:00:00Z" },
  ] as WorkspacePerson[],
  projects: [
    { id: "project-maeglagi", workspaceId: "demo", name: "맥락이 PoC", goal: "조직의 회의와 자료를 연결", description: "검증 프로젝트", ownerPersonId: "person-minkyu", participantIds: ["person-minkyu", "person-heewon"], revision: 0, startsOn: "2026-09-08", endsOn: null, archivedAt: null, createdAt: "2026-09-08T09:00:00Z", updatedAt: "2026-09-08T09:00:00Z" },
  ] as WorkspaceProject[],
  reviews: new Map<string, MeetingReview>(),
  /** 계정 연결의 키 원문은 보관하지 않고 응답 힌트만 흉내 냅니다. */
  accountCredentials: [{
    id: "demo-credential",
    provider: "anthropic",
    label: "기본",
    keyHint: "4f2a",
    status: "active",
    isDefault: true,
    updatedAt: "2026-09-08T09:00:00Z",
  }] as WorkspaceSecrets[],
  /** 계정 MCP 토큰의 메타데이터만 유지합니다. */
  mcpTokens: [] as McpToken[],
  /** 워크스페이스별로 저장된 모델 선택 */
  models: new Map<string, ModelSelections>([
    ["demo", { answer: { provider: "anthropic", model: "claude-sonnet-4-20250514" } }],
  ]),
};

const MODEL_ROLES: ModelRole[] = ["answer", "extraction", "embedding", "transcription"];

/** 키 하나로 쓸 수 있는 모델을 용도별로 묶습니다. 선택이 있으면 함께 담습니다. */
function modelsFor(
  provider: LlmProvider,
  selections: ModelSelections = {},
  locked: ModelRole[] = [],
): WorkspaceModels {
  return modelsForProviders([provider], selections, locked);
}

function modelsForProviders(
  providers: LlmProvider[],
  selections: ModelSelections = {},
  locked: ModelRole[] = [],
  credentials?: WorkspaceSecrets[],
): WorkspaceModels {
  return {
    roles: MODEL_ROLES.map((role) => ({
      role,
      options: providers.flatMap((provider) =>
        (credentials ? credentials.filter((item) => item.provider === provider) : [undefined]).flatMap((credential) =>
          (modelCatalog[provider]?.[role] ?? []).map((model) => ({ provider, model, ...(credential ? { credentialId: credential.id } : {}) })),
        ),
      ),
      selected: selections[role] ?? null,
      locked: locked.includes(role),
    })),
  };
}

/**
 * 임베딩 모델은 워크스페이스를 만들 때 정하고 바꿀 수 없습니다(백엔드와 같은 규칙).
 * 선택이 이미 있거나 소스가 색인된 뒤에는 잠기고, LLM 모델은 언제든 바꿀 수 있습니다.
 */
function lockedRoles(workspaceId: string): ModelRole[] {
  const chosen = state.models.get(workspaceId)?.embedding !== undefined;
  const indexed = state.sources.some(
    (source) => source.workspaceId === workspaceId && source.status === "succeeded",
  );
  return chosen || indexed ? ["embedding"] : [];
}

/** provider별 키 접두사. 실제 서비스의 키 형식과 맞춥니다. */
const keyPrefix: Record<string, string> = {
  anthropic: "sk-ant-",
  nvidia: "nvapi-",
  openai: "sk-",
};

/**
 * 키 검증을 흉내 냅니다.
 *
 * 실제 서버는 provider에 호출을 보내 확인하므로, 형식이 맞아도 실패할 수
 * 있습니다. mock은 접두사와 길이만 봅니다.
 */
function checkApiKey(provider: LlmProvider, apiKey: string, baseUrl?: string): ApiKeyValidation {
  const key = apiKey.trim();

  if (provider === "ollama") {
    try {
      const url = new URL(baseUrl ?? "");
      if (!["http:", "https:"].includes(url.protocol) || !url.hostname || url.username || url.password || url.search || url.hash) throw new Error();
    } catch {
      return { valid: false, message: "Ollama 서버 주소를 확인해 주세요." };
    }
    return { valid: true, message: "Ollama 서버 연결을 확인했습니다. (모의 응답)" };
  }

  if (!key) return { valid: false, message: "API key를 입력해 주세요." };
  const prefix = keyPrefix[provider];
  if (prefix && !key.startsWith(prefix)) {
    return {
      valid: false,
      message: `${provider} 키는 ${prefix}로 시작해야 합니다.`,
    };
  }
  // anthropic 키도 "sk-"로 시작하므로 provider를 잘못 고른 경우를 따로 잡습니다.
  if (provider === "openai" && key.startsWith(keyPrefix.anthropic)) {
    return { valid: false, message: "Anthropic 키로 보입니다. provider를 확인해 주세요." };
  }
  if (key.length < 20) return { valid: false, message: "키 길이가 올바르지 않습니다." };

  return { valid: true, message: "정상적으로 확인했습니다." };
}

function storeKey(
  _workspaceId: string,
  provider: LlmProvider,
  apiKey: string | undefined,
  label = "기본",
  baseUrl?: string,
): WorkspaceSecrets {
  const credentials = state.accountCredentials;
  const existing = credentials.find((item) => item.provider === provider && item.label === label);
  for (const item of credentials) item.isDefault = false;
  const secrets: WorkspaceSecrets = {
    id: existing?.id ?? nextId("credential"),
    provider,
    label,
    keyHint: apiKey === undefined ? existing?.keyHint ?? "none" : provider === "ollama" ? (apiKey.trim() ? "configured" : "none") : apiKey.trim().slice(-4),
    baseUrl: baseUrl ?? existing?.baseUrl ?? null,
    status: "active",
    isDefault: true,
    updatedAt: new Date().toISOString(),
  };
  if (existing) credentials.splice(credentials.indexOf(existing), 1, secrets);
  else credentials.push(secrets);
  return secrets;
}

let sequence = 0;
const nextId = (prefix: string) => `${prefix}-${++sequence}`;

/** 경과 시간으로 진행률과 단계를 계산합니다. */
function advanceJob(job: ProcessingJob & { startedAt: number }): ProcessingJob {
  if (job.status === "awaiting_review" || job.status === "failed") {
    const { startedAt: _startedAt, ...rest } = job;
    return { ...rest };
  }
  const review = state.reviews.get(job.sourceId);
  if (review?.reviewState === "transcribing" && Date.now() - job.startedAt >= JOB_DURATION_MS / 2) {
    review.reviewState = "awaiting_review";
    review.status = "awaiting_review";
    review.stage = "awaiting_review";
    review.errorMessage = null;
    review.rawTranscriptText = "화자 1: 회의 녹음의 서버 음성 인식 초안입니다. 내용을 확인해 주세요.";
    review.rawUtterances = [{ id: nextId("utterance"), personId: null, speakerName: "화자 1", text: "회의 녹음의 서버 음성 인식 초안입니다. 내용을 확인해 주세요.", startSeconds: 0 }];
    if (!review.utterances.length) review.utterances = structuredClone(review.rawUtterances);
    job.status = "awaiting_review";
    job.stage = "awaiting_review";
    job.progress = 0.5;
    const source = state.sources.find((item) => item.id === job.sourceId);
    if (source) source.status = "awaiting_review";
    const { startedAt: _startedAt, ...rest } = job;
    return { ...rest };
  }
  const stages = review?.reviewState === "confirmed"
    ? (["analyzing", "graphing", "completed"] as const)
    : job.transcriptSource === "browser"
      ? (["uploaded", "analyzing", "graphing", "completed"] as const)
      : stageSequence[job.sourceKind];
  const elapsed = Date.now() - job.startedAt;
  const ratio = Math.min(elapsed / JOB_DURATION_MS, 1);

  // 마지막 `completed`는 진행률 100%에서만 들어갑니다.
  const workStages = stages.length - 1;
  const stageIndex =
    ratio >= 1 ? workStages : Math.min(Math.floor(ratio * workStages), workStages - 1);

  job.progress = ratio;
  job.stage = stages[stageIndex];
  job.status = ratio >= 1 ? "succeeded" : "processing";

  if (job.status === "succeeded") {
    const source = state.sources.find((item) => item.id === job.sourceId);
    if (source) source.status = "succeeded";
  }

  const { startedAt: _startedAt, ...rest } = job;
  return { ...rest };
}

/** 실제 업로드처럼 보이도록 전송 진행률을 단계적으로 올립니다. */
async function simulateTransfer({ signal, onProgress }: UploadOptions = {}): Promise<void> {
  const steps = 12;
  for (let step = 1; step <= steps; step += 1) {
    await delay(MOCK_LATENCY_MS / steps, signal);
    onProgress?.(step / steps);
  }
}

function registerUpload(workspaceId: string, source: Source): ProcessingJob {
  state.sources.unshift(source);

  const workspace = state.workspaces.find((item) => item.id === workspaceId);
  if (workspace) workspace.sourceCount += 1;

  const job: ProcessingJob & { startedAt: number } = {
    id: source.id,
    sourceId: source.id,
    sourceKind: source.kind,
    transcriptSource: source.transcriptSource,
    status: "queued",
    progress: 0,
    stage: "uploaded",
    startedAt: Date.now(),
  };
  state.jobs.set(job.id, job);

  const { startedAt: _startedAt, ...rest } = job;
  return { ...rest };
}

/** 백엔드 없이 모든 화면을 개발할 수 있게 하는 in-memory 구현입니다. */
export const mockApi: MaeglagiApi = {
  async listMcpTokens(signal) {
    await delay(MOCK_LATENCY_MS, signal);
    return { items: state.mcpTokens.map((item) => ({ ...item })) };
  },

  async createMcpToken(input, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const label = input.label.trim();
    if (!label) throw new ApiError(422, "토큰 이름을 입력해 주세요.");
    if (!Number.isInteger(input.expiresInDays) || input.expiresInDays < 1 || input.expiresInDays > 365) {
      throw new ApiError(422, "토큰 유효 기간은 1~365일로 설정해 주세요.");
    }
    const token = `mcp_mock_${crypto.randomUUID().replaceAll("-", "")}`;
    const now = new Date();
    const item = {
      id: nextId("mcp-token"),
      label,
      tokenHint: token.slice(-6),
      createdAt: now.toISOString(),
      lastUsedAt: null,
      expiresAt: new Date(now.getTime() + input.expiresInDays * 24 * 60 * 60 * 1000).toISOString(),
    };
    state.mcpTokens.unshift(item);
    return { item: { ...item }, token };
  },

  async revokeMcpToken(tokenId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const index = state.mcpTokens.findIndex((item) => item.id === tokenId);
    if (index < 0) throw new ApiError(404, "토큰을 찾을 수 없습니다.");
    state.mcpTokens.splice(index, 1);
  },

  async listWorkspaces(signal) {
    await delay(MOCK_LATENCY_MS, signal);
    return state.workspaces.map((workspace) => ({ ...workspace }));
  },

  async getWorkspace(workspaceId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const workspace = state.workspaces.find((item) => item.id === workspaceId);
    if (!workspace) throw new ApiError(404, "워크스페이스를 찾을 수 없습니다.");
    return { ...workspace };
  },

  async createWorkspace(input, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    if (!input.name.trim()) throw new ApiError(422, "워크스페이스 이름을 입력해 주세요.");
    const chosenCredential = input.credentialId
      ? state.accountCredentials.find((item) => item.id === input.credentialId && item.status === "active")
      : undefined;
    if (input.credentialId && (!chosenCredential || (input.llmProvider && chosenCredential.provider !== input.llmProvider))) throw new ApiError(422, "사용 가능한 계정 AI 연결을 선택해 주세요.");
    const provider = chosenCredential?.provider ?? input.llmProvider;
    if (!provider && (input.llmApiKey || input.models)) throw new ApiError(422, "AI 연결을 선택해 주세요.");
    if (provider && !input.credentialId) {
      if (provider !== "ollama" && !input.llmApiKey?.trim()) throw new ApiError(422, "API key를 입력해 주세요.");
      const check = checkApiKey(provider, input.llmApiKey ?? "", input.llmBaseUrl);
      if (!check.valid) throw new ApiError(422, check.message);
    }

    const workspace: Workspace = {
      id: nextId("ws"),
      name: input.name.trim(),
      createdAt: new Date().toISOString(),
      sourceCount: 0,
    };
    state.workspaces.push(workspace);

    // BYOK 키는 저장만 하고 어떤 응답에도 포함하지 않습니다.
    if (provider && !input.credentialId) storeKey(workspace.id, provider, input.llmApiKey ?? "", "기본", input.llmBaseUrl);
    if (input.models) state.models.set(workspace.id, { ...input.models });
    return { ...workspace };
  },

  async cloneDemoWorkspace() {
    throw new ApiError(501, "데모 복사는 실제 API 모드에서만 사용할 수 있습니다.");
  },

  async listProviders(signal) {
    await delay(MOCK_LATENCY_MS, signal);
    return BOOTSTRAP_AI_PROVIDERS.map<AiProvider>((provider) => ({
      ...provider,
      capabilities: [...provider.capabilities],
    }));
  },

  async listWorkspaceProviders(workspaceId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    if (!state.workspaces.some((item) => item.id === workspaceId)) {
      throw new ApiError(404, "워크스페이스를 찾을 수 없습니다.");
    }

    const configuredProviders = state.accountCredentials;
    return BOOTSTRAP_AI_PROVIDERS.map<AiProvider>((provider) => ({
      ...provider,
      capabilities: [...provider.capabilities],
      configured: configuredProviders.some(
        (item) => item.provider === provider.id && item.status === "active",
      ),
      models: configuredProviders.some(
        (item) => item.provider === provider.id && item.status === "active",
      )
        ? provider.id === "anthropic"
          ? ["claude-sonnet-4-20250514"]
          : provider.id === "nvidia"
            ? ["meta/llama-3.1-70b-instruct"]
            : provider.id === "ollama"
              ? ["llama3.2:latest"]
              : ["gpt-4.1-mini"]
        : [],
    }));
  },

  async validateApiKey(input, signal) {
    // 실제 provider 호출을 흉내 내느라 조금 더 걸립니다.
    await delay(MOCK_LATENCY_MS * 2, signal);
    return checkApiKey(input.provider, input.apiKey ?? "", input.baseUrl);
  },

  async listKeyModels(input, signal) {
    await delay(MOCK_LATENCY_MS * 2, signal);
    if (input.credentialId) {
      const credential = state.accountCredentials.find((item) => item.id === input.credentialId && item.provider === input.provider && item.status === "active");
      if (!credential) throw new ApiError(404, "계정 AI 연결을 찾을 수 없습니다.");
      return modelsForProviders([input.provider], {}, [], [credential]);
    }
    const check = checkApiKey(input.provider, input.apiKey ?? "", input.baseUrl);
    if (!check.valid) throw new ApiError(422, check.message);
    return modelsFor(input.provider);
  },

  async getWorkspaceModels(workspaceId, provider, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const credentials = state.accountCredentials;
    if (!state.workspaces.some((item) => item.id === workspaceId)) {
      throw new ApiError(404, "워크스페이스를 찾을 수 없습니다.");
    }
    const activeProviders = [
      ...new Set(
        credentials.filter((item) => item.status === "active").map((item) => item.provider),
      ),
    ];
    const visibleProviders = provider
      ? activeProviders.filter((item) => item === provider)
      : activeProviders;
    return modelsForProviders(
      visibleProviders,
      state.models.get(workspaceId),
      lockedRoles(workspaceId),
      credentials.filter((item) => item.status === "active"),
    );
  },

  async updateWorkspaceModels(workspaceId, selections, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const credentials = state.accountCredentials;
    if (!state.workspaces.some((item) => item.id === workspaceId) || credentials.length === 0) {
      throw new ApiError(404, "워크스페이스를 찾을 수 없습니다.");
    }

    const currentSelections = state.models.get(workspaceId) ?? {};
    const next: ModelSelections = { ...state.models.get(workspaceId) };
    for (const role of MODEL_ROLES) {
      const wanted = selections[role];
      if (!wanted) continue;
      const entry = modelsForProviders(
        [wanted.provider],
        currentSelections,
        lockedRoles(workspaceId),
        credentials.filter((item) => item.status === "active"),
      ).roles.find((item) => item.role === role)!;
      if (
        !credentials.some((item) => item.provider === wanted.provider && item.status === "active")
      ) {
        throw new ApiError(422, "사용 가능한 API key가 없습니다.");
      }
      if (!entry.options.some((o) => o.provider === wanted.provider && o.model === wanted.model && (!wanted.credentialId || o.credentialId === wanted.credentialId))) {
        throw new ApiError(422, `${wanted.model}은(는) 이 키로 쓸 수 있는 모델이 아닙니다.`);
      }
      const unchanged =
        entry.selected?.provider === wanted.provider && entry.selected.model === wanted.model &&
        (entry.selected.credentialId ?? null) === (wanted.credentialId ?? null);
      if (entry.locked && !unchanged) {
        throw new ApiError(409, "임베딩 모델은 워크스페이스를 만들 때 정해지며 바꿀 수 없습니다.");
      }
      next[role] = wanted;
    }
    state.models.set(workspaceId, next);
    return modelsForProviders(
      [
        ...new Set(
          credentials.filter((item) => item.status === "active").map((item) => item.provider),
        ),
      ],
      next,
      lockedRoles(workspaceId),
      credentials.filter((item) => item.status === "active"),
    );
  },

  async getWorkspaceSecrets(workspaceId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    return state.accountCredentials.find((item) => item.isDefault) ?? null;
  },

  async listProviderCredentials(workspaceId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    if (!state.workspaces.some((item) => item.id === workspaceId))
      throw new ApiError(404, "워크스페이스를 찾을 수 없습니다.");
    return state.accountCredentials.map((item) => ({ ...item }));
  },

  async listAccountCredentials(signal) {
    await delay(MOCK_LATENCY_MS, signal);
    return state.accountCredentials.map((item) => ({ ...item }));
  },

  async createAccountCredential(input, signal) {
    await delay(MOCK_LATENCY_MS * 2, signal);
    if (!input.label.trim()) throw new ApiError(422, "연결 이름을 입력해 주세요.");
    if (state.accountCredentials.some((item) => item.provider === input.provider && item.label === input.label.trim())) throw new ApiError(409, "같은 이름의 연결이 있습니다.");
    const check = checkApiKey(input.provider, input.apiKey ?? "", input.baseUrl);
    if (!check.valid) throw new ApiError(422, check.message);
    return { ...storeKey("account", input.provider, input.apiKey ?? "", input.label.trim(), input.baseUrl) };
  },

  async rotateAccountCredential(credentialId, input, signal) {
    await delay(MOCK_LATENCY_MS * 2, signal);
    const credential = state.accountCredentials.find((item) => item.id === credentialId);
    if (!credential) throw new ApiError(404, "연결을 찾을 수 없습니다.");
    const check = checkApiKey(credential.provider, input.apiKey ?? (credential.provider === "ollama" ? "" : "retained-secret"), input.baseUrl ?? credential.baseUrl ?? undefined);
    if (!check.valid) throw new ApiError(422, check.message);
    credential.baseUrl = input.baseUrl ?? credential.baseUrl;
    if (input.apiKey !== undefined) credential.keyHint = credential.provider === "ollama" ? (input.apiKey.trim() ? "configured" : "none") : input.apiKey.trim().slice(-4);
    credential.updatedAt = new Date().toISOString();
    return { ...credential };
  },

  async setDefaultAccountCredential(credentialId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const credential = state.accountCredentials.find((item) => item.id === credentialId);
    if (!credential) throw new ApiError(404, "연결을 찾을 수 없습니다.", { detail: "Credential not found" });
    if (credential.status !== "active") {
      throw new ApiError(409, "활성 상태인 연결만 기본으로 지정할 수 있습니다.", { detail: "Credential is not active" });
    }
    for (const item of state.accountCredentials) item.isDefault = item.id === credentialId;
    credential.updatedAt = new Date().toISOString();
    return { ...credential };
  },

  // 거절 규칙과 `detail` 원문은 백엔드 remove_credential과 같게 둡니다. 화면이 이 원문으로 문구를 고릅니다.
  async deleteAccountCredential(credentialId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const credentials = state.accountCredentials;
    const credential = credentials.find((item) => item.id === credentialId);
    if (!credential) throw new ApiError(404, "연결을 찾을 수 없습니다.", { detail: "Credential not found" });
    const refuse = (detail: string) => new ApiError(409, "이 연결은 지금 삭제할 수 없습니다.", { detail });
    if (credential.isDefault && credentials.length > 1) throw refuse("Choose another default before deletion");
    const selections = [...state.models.values()].flatMap((chosen) => Object.values(chosen));
    if (selections.some((option) => option.credentialId === credentialId)) {
      throw refuse("This credential is selected by a workspace model");
    }
    const hasSibling = credentials.some(
      (item) => item.id !== credentialId && item.provider === credential.provider && item.status === "active",
    );
    if (!hasSibling && selections.some((option) => option.provider === credential.provider)) {
      throw refuse("This is the last active credential for a selected model provider");
    }
    credentials.splice(credentials.indexOf(credential), 1);
  },

  async updateApiKey(workspaceId, input, signal) {
    await delay(MOCK_LATENCY_MS * 2, signal);
    if (!state.workspaces.some((item) => item.id === workspaceId)) {
      throw new ApiError(404, "워크스페이스를 찾을 수 없습니다.");
    }

    const check = checkApiKey(input.provider, input.apiKey ?? "", input.baseUrl);
    if (!check.valid) throw new ApiError(422, check.message);

    const saved = storeKey(workspaceId, input.provider, input.apiKey, input.label, input.baseUrl);
    return saved;
  },

  async rotateProviderCredential(workspaceId, credentialId, input, signal) {
    await delay(MOCK_LATENCY_MS * 2, signal);
    const credential = state.accountCredentials.find((item) => item.id === credentialId);
    if (!credential) throw new ApiError(404, "연결을 찾을 수 없습니다.");
    const check = checkApiKey(credential.provider, input.apiKey ?? (["none", "local"].includes(credential.keyHint) ? "" : "retained-secret"), input.baseUrl ?? credential.baseUrl ?? undefined);
    if (!check.valid) throw new ApiError(422, check.message);
    credential.baseUrl = input.baseUrl ?? credential.baseUrl;
    if (input.apiKey !== undefined) credential.keyHint = credential.provider === "ollama" ? (input.apiKey.trim() ? "configured" : "none") : input.apiKey.trim().slice(-4);
    credential.updatedAt = new Date().toISOString();
    return { ...credential };
  },

  async listPeople(workspaceId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    return state.people.filter((item) => item.workspaceId === workspaceId).map((item) => structuredClone(item));
  },
  async createPerson(workspaceId, input, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    if (!input.name.trim()) throw new ApiError(422, "이름을 입력해 주세요.");
    const email = input.email?.trim().toLowerCase() || null;
    const existing = email && state.people.find((person) => person.workspaceId === workspaceId && person.email?.toLowerCase() === email);
    if (existing) return structuredClone(existing);
    const now = new Date().toISOString();
    const item: WorkspacePerson = { id: nextId("person"), workspaceId, name: input.name.trim(), email, aliases: input.aliases ?? [], role: input.role ?? null, archivedAt: null, createdAt: now, updatedAt: now };
    state.people.push(item);
    return structuredClone(item);
  },
  async updatePerson(workspaceId, personId, input, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const item = state.people.find((person) => person.workspaceId === workspaceId && person.id === personId);
    if (!item) throw new ApiError(404, "참여자를 찾을 수 없습니다.");
    if (input.name !== undefined) item.name = input.name.trim();
    if (input.email !== undefined) item.email = input.email?.trim().toLowerCase() || null;
    if (input.aliases !== undefined) item.aliases = input.aliases;
    if (input.role !== undefined) item.role = input.role;
    if (input.archived !== undefined) item.archivedAt = input.archived ? new Date().toISOString() : null;
    item.updatedAt = new Date().toISOString();
    return structuredClone(item);
  },
  async listProjects(workspaceId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    return state.projects.filter((item) => item.workspaceId === workspaceId).map((item) => structuredClone(item));
  },
  async createProject(workspaceId, input, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    if (!input.name.trim()) throw new ApiError(422, "프로젝트 이름을 입력해 주세요.");
    if (input.endsOn && input.startsOn && input.endsOn < input.startsOn) throw new ApiError(422, "종료일은 시작일보다 빠를 수 없습니다.");
    if (input.ownerPersonId && !state.people.some((item) => item.id === input.ownerPersonId && item.workspaceId === workspaceId && !item.archivedAt)) throw new ApiError(422, "활성 참여자를 담당자로 선택해 주세요.");
    const now = new Date().toISOString();
    const item: WorkspaceProject = { id: nextId("project"), workspaceId, name: input.name.trim(), goal: input.goal ?? null, description: input.description ?? null, ownerPersonId: input.ownerPersonId ?? null, participantIds: [...new Set(input.participantIds ?? [])], revision: 0, startsOn: input.startsOn ?? null, endsOn: input.endsOn ?? null, archivedAt: null, createdAt: now, updatedAt: now };
    state.projects.push(item);
    return structuredClone(item);
  },
  async updateProject(workspaceId, projectId, input, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const item = state.projects.find((project) => project.workspaceId === workspaceId && project.id === projectId);
    if (!item) throw new ApiError(404, "프로젝트를 찾을 수 없습니다.");
    const start = input.startsOn === undefined ? item.startsOn : input.startsOn;
    const end = input.endsOn === undefined ? item.endsOn : input.endsOn;
    if (start && end && end < start) throw new ApiError(422, "종료일은 시작일보다 빠를 수 없습니다.");
    if (input.ownerPersonId && !state.people.some((person) => person.id === input.ownerPersonId && person.workspaceId === workspaceId && !person.archivedAt)) throw new ApiError(422, "활성 참여자를 담당자로 선택해 주세요.");
    Object.assign(item, input);
    if (input.participantIds !== undefined) item.participantIds = [...new Set(input.participantIds)];
    item.revision = (item.revision ?? 0) + 1;
    if (input.archived !== undefined) item.archivedAt = input.archived ? new Date().toISOString() : null;
    item.updatedAt = new Date().toISOString();
    return structuredClone(item);
  },
  async listProjectParticipants(workspaceId, projectId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const project = state.projects.find((item) => item.workspaceId === workspaceId && item.id === projectId);
    if (!project) throw new ApiError(404, "프로젝트를 찾을 수 없습니다.");
    return structuredClone(state.people.filter((person) => (project.participantIds ?? []).includes(person.id)));
  },
  async setProjectParticipants(workspaceId, projectId, input, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const project = state.projects.find((item) => item.workspaceId === workspaceId && item.id === projectId);
    if (!project) throw new ApiError(404, "프로젝트를 찾을 수 없습니다.");
    if ((project.revision ?? 0) !== input.revision) throw new ApiError(409, "프로젝트가 변경됐습니다.");
    if (input.personIds.some((id) => !state.people.some((person) => person.id === id && person.workspaceId === workspaceId && !person.archivedAt))) throw new ApiError(422, "활성 참여자를 선택해 주세요.");
    project.participantIds = [...new Set(input.personIds)];
    project.revision = (project.revision ?? 0) + 1;
    project.updatedAt = new Date().toISOString();
    return structuredClone(project);
  },

  async listSources(workspaceId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    return state.sources
      .filter((source) => source.workspaceId === workspaceId)
      .map((source) => ({ ...source }));
  },

  async getSourceContent(sourceId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const source = state.sources.find((item) => item.id === sourceId);
    if (!source) throw new ApiError(404, "원문을 찾을 수 없습니다.");
    const content = sourceContents.find((item) => item.sourceId === sourceId);
    const review = state.reviews.get(sourceId);
    const utterances = review?.utterances ?? content?.utterances ?? [];
    const editedText = utterances.filter((item) => item.text.trim()).map((item) => `${item.speakerName}: ${item.text}`).join("\n\n");
    return structuredClone({
      sourceId,
      title: source.title,
      kind: source.kind,
      hasRecording: state.recordings.has(sourceId),
      originalText: editedText || review?.rawTranscriptText || content?.originalText || null,
      utterances,
      chunks: content?.chunks ?? [],
    } satisfies SourceContent);
  },
  async getSourcePlaybackUrl(sourceId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const audio = state.recordings.get(sourceId);
    if (!audio) throw new ApiError(404, "저장된 녹음이 없습니다.");
    return { url: URL.createObjectURL(audio), expiresAt: new Date(Date.now() + 3600_000).toISOString() };
  },
  async exportSourceMarkdown(sourceId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const review = state.reviews.get(sourceId);
    if (!review) throw new ApiError(404, "회의 대본을 찾을 수 없습니다.");
    if (review.reviewState !== "confirmed") throw new ApiError(409, "확인된 대본만 내보낼 수 있습니다.");
    const lines = [`# ${review.title}`, "", ...review.utterances.filter((item) => item.text.trim()).flatMap((item) => [`## ${item.speakerName}`, item.text.trim(), ""])];
    return new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" });
  },
  async updateSourceAssociations(workspaceId, sourceId, input, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const source = state.sources.find((item) => item.workspaceId === workspaceId && item.id === sourceId);
    if (!source) throw new ApiError(404, "소스를 찾을 수 없습니다.");
    if ((source.associationRevision ?? 0) !== input.revision) throw new ApiError(409, "소스 정보가 변경됐습니다.");
    if (input.projectIds.some((id) => !state.projects.some((project) => project.id === id && project.workspaceId === workspaceId && !project.archivedAt))) throw new ApiError(422, "활성 프로젝트를 선택해 주세요.");
    if (input.people.some((item) => !state.people.some((person) => person.id === item.personId && person.workspaceId === workspaceId && !person.archivedAt))) throw new ApiError(422, "활성 참여자를 선택해 주세요.");
    source.projectIds = [...new Set(input.projectIds)];
    source.projectId = source.projectIds[0] ?? null;
    source.associations = structuredClone(input.people);
    source.associationRevision = (source.associationRevision ?? 0) + 1;
    return { revision: source.associationRevision, projectIds: structuredClone(source.projectIds), people: structuredClone(source.associations) };
  },

  async uploadDocument(workspaceId, file, options) {
    await simulateTransfer(options);
    return registerUpload(workspaceId, {
      id: nextId("src"),
      workspaceId,
      kind: "document",
      title: file.name,
      status: "processing",
      createdAt: new Date().toISOString(),
      sizeBytes: file.size,
    });
  },

  async uploadRecording(workspaceId, audio, liveDraft, projectId, options) {
    await simulateTransfer(options);
    if (projectId && !state.projects.some((item) => item.id === projectId && item.workspaceId === workspaceId && !item.archivedAt)) throw new ApiError(422, "활성 프로젝트를 선택해 주세요.");
    const projectIds = [...new Set(options?.projectIds ?? (projectId ? [projectId] : []))];
    if (projectIds.some((id) => !state.projects.some((item) => item.id === id && item.workspaceId === workspaceId && !item.archivedAt))) throw new ApiError(422, "활성 프로젝트를 선택해 주세요.");
    const job = registerUpload(workspaceId, {
      id: nextId("src"),
      workspaceId,
      kind: "meeting",
      title: `회의 녹음 ${new Date().toLocaleString("ko-KR")}`,
      status: "processing",
      createdAt: new Date().toISOString(),
      // Blob에는 길이 정보가 없으므로 대략치로 둡니다. 실제 값은 STT가 채웁니다.
      durationSeconds: Math.round(audio.size / 16_000),
      transcriptSource: "server",
      projectId: projectId ?? null,
      projectIds,
      hasRecording: true,
      associations: [],
      associationRevision: 0,
    });
    state.recordings.set(job.sourceId, audio);
    job.transcriptSource = "server";
    state.reviews.set(job.sourceId, { sourceId: job.sourceId, title: state.sources.find((item) => item.id === job.sourceId)?.title ?? "회의 녹음", transcriptSource: "server", reviewState: "transcribing", status: "queued", stage: "transcribing", errorMessage: null, revision: 0, projectId: projectId ?? null, projectIds, suggestedParticipants: state.people.filter((person) => projectIds.some((id) => state.projects.find((project) => project.id === id)?.participantIds?.includes(person.id))), utterances: structuredClone(liveDraft?.utterances ?? []), rawTranscriptText: null, rawUtterances: [], confirmedAt: null, confirmedSnapshot: null });
    return job;
  },

  async uploadTranscript(workspaceId, input, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    if (!input.text.trim()) throw new ApiError(422, "대본을 입력해 주세요.");
    const projectIds = [...new Set(input.projectIds ?? (input.projectId ? [input.projectId] : []))];
    if (projectIds.some((id) => !state.projects.some((item) => item.id === id && item.workspaceId === workspaceId && !item.archivedAt))) throw new ApiError(422, "활성 프로젝트를 선택해 주세요.");
    const job = registerUpload(workspaceId, {
      id: nextId("src"),
      workspaceId,
      kind: "meeting",
      title: input.title?.trim() || `회의 대본 ${new Date().toLocaleString("ko-KR")}`,
      status: "awaiting_review",
      createdAt: new Date().toISOString(),
      durationSeconds: input.durationSeconds,
      transcriptSource: "browser",
      projectId: input.projectId ?? null,
      projectIds,
      hasRecording: false,
      associations: [],
      associationRevision: 0,
    });
    state.reviews.set(job.sourceId, { sourceId: job.sourceId, title: input.title?.trim() || "회의 대본", transcriptSource: "browser", reviewState: "awaiting_review", status: "awaiting_review", stage: "awaiting_review", errorMessage: null, revision: 0, projectId: input.projectId ?? null, projectIds, suggestedParticipants: state.people.filter((person) => projectIds.some((id) => state.projects.find((project) => project.id === id)?.participantIds?.includes(person.id))), utterances: structuredClone(input.utterances?.length ? input.utterances : [{ id: nextId("utterance"), personId: null, speakerName: "화자 1", text: input.text }]), rawTranscriptText: input.text, rawUtterances: structuredClone(input.utterances ?? []), confirmedAt: null, confirmedSnapshot: null });
    const storedJob = state.jobs.get(job.id)!;
    storedJob.status = "awaiting_review";
    storedJob.stage = "awaiting_review";
    storedJob.progress = 0.5;
    job.status = "awaiting_review";
    job.stage = "awaiting_review";
    job.progress = 0.5;
    job.transcriptSource = "browser";
    return job;
  },

  async getJob(jobId, signal) {
    await delay(120, signal);
    const job = state.jobs.get(jobId);
    if (!job) throw new ApiError(404, "처리 작업을 찾을 수 없습니다.");
    return advanceJob(job);
  },
  async *sourceEvents(workspaceId, sourceIds, signal) {
    if (sourceIds.length < 1 || sourceIds.length > 100) throw new ApiError(422, "소스는 1~100개를 선택해 주세요.");
    const selected = new Set(sourceIds);
    const seen = new Map<string, string>();
    while (!signal?.aborted) {
      for (const job of state.jobs.values()) {
        if (!selected.has(job.sourceId) || !state.sources.some((source) => source.id === job.sourceId && source.workspaceId === workspaceId)) continue;
        const current = advanceJob(job);
        const fingerprint = JSON.stringify(current);
        if (seen.get(job.id) !== fingerprint) { seen.set(job.id, fingerprint); yield current; }
      }
      await delay(300, signal);
    }
  },
  async getMeetingReview(workspaceId, sourceId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const review = state.reviews.get(sourceId);
    if (!review || !state.sources.some((item) => item.id === sourceId && item.workspaceId === workspaceId)) throw new ApiError(404, "검토 대본을 찾을 수 없습니다.");
    const job = state.jobs.get(sourceId);
    const currentJob = job ? advanceJob(job) : undefined;
    return { ...structuredClone(review), status: currentJob?.status ?? review.status, stage: currentJob?.stage ?? review.stage, errorMessage: currentJob?.errorMessage ?? review.errorMessage };
  },
  async retryMeetingTranscription(workspaceId, sourceId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const review = state.reviews.get(sourceId);
    const job = state.jobs.get(sourceId);
    const source = state.sources.find((item) => item.id === sourceId && item.workspaceId === workspaceId);
    if (!review || !job || !source || source.kind !== "meeting" || review.transcriptSource !== "server") throw new ApiError(404, "검토 대본을 찾을 수 없습니다.");
    if (review.reviewState !== "transcribing") throw new ApiError(409, "이미 검토 단계로 이동한 대본입니다.");
    if (job.status === "queued" || job.status === "enqueue_pending" || job.status === "processing") return advanceJob(job);
    if (job.status !== "failed") throw new ApiError(409, "다시 시도할 수 없는 상태입니다.");
    job.status = "queued";
    job.stage = "transcribing";
    job.progress = 0;
    job.errorMessage = undefined;
    job.startedAt = Date.now();
    source.status = "queued";
    review.status = "queued";
    review.stage = "transcribing";
    review.errorMessage = null;
    const { startedAt: _startedAt, ...response } = job;
    return { ...response };
  },
  async submitBrowserTranscript(workspaceId, sourceId, input, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const review = state.reviews.get(sourceId);
    const source = state.sources.find((item) => item.id === sourceId && item.workspaceId === workspaceId);
    const job = state.jobs.get(sourceId);
    if (!review || !source || !job || source.kind !== "meeting") throw new ApiError(404, "검토 대본을 찾을 수 없습니다.");
    if (review.revision !== input.revision || review.reviewState !== "transcribing" || job.status !== "failed" || review.analysisMode === "agent") throw new ApiError(409, "음성 인식 상태가 변경됐습니다. 다시 불러와 주세요.");
    if (!input.utterances.some((item) => item.text.trim())) throw new ApiError(422, "완성된 발언이 없습니다.");
    review.utterances = structuredClone(input.utterances);
    if (!review.rawTranscriptText) {
      review.rawUtterances = structuredClone(input.utterances);
      review.rawTranscriptText = input.utterances.map((item) => `${item.speakerName}: ${item.text}`).join("\n\n");
    }
    review.transcriptSource = "browser";
    review.reviewState = "awaiting_review";
    review.status = "awaiting_review";
    review.stage = "awaiting_review";
    review.errorMessage = null;
    review.revision += 1;
    source.status = "awaiting_review";
    job.status = "awaiting_review";
    job.stage = "awaiting_review";
    job.transcriptSource = "browser";
    return structuredClone(review);
  },
  async saveMeetingReview(workspaceId, sourceId, input, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const review = state.reviews.get(sourceId);
    if (!review || !state.sources.some((item) => item.id === sourceId && item.workspaceId === workspaceId)) throw new ApiError(404, "검토 대본을 찾을 수 없습니다.");
    if (review.reviewState !== "awaiting_review" || review.revision !== input.revision) throw new ApiError(409, "대본이 변경됐습니다. 다시 불러와 주세요.");
    const projectIds = [...new Set(input.projectIds ?? (input.projectId ? [input.projectId] : []))];
    if (projectIds.some((id) => !state.projects.some((item) => item.id === id && item.workspaceId === workspaceId && !item.archivedAt))) throw new ApiError(422, "활성 프로젝트를 선택해 주세요.");
    const source = state.sources.find((item) => item.id === sourceId);
    const ids = input.utterances.map((item) => item.id);
    if (new Set(ids).size !== ids.length) throw new ApiError(422, "발언 ID가 중복됐습니다.");
    if (input.utterances.some((item) => item.personId && !state.people.some((person) => person.id === item.personId && person.workspaceId === source?.workspaceId && !person.archivedAt))) throw new ApiError(422, "활성 참여자를 화자로 선택해 주세요.");
    review.projectId = projectIds[0] ?? null;
    review.projectIds = projectIds;
    review.suggestedParticipants = state.people.filter((person) => projectIds.some((id) => state.projects.find((project) => project.id === id)?.participantIds?.includes(person.id)));
    if (source) { source.projectId = review.projectId; source.projectIds = projectIds; }
    review.utterances = structuredClone(input.utterances);
    review.revision += 1;
    review.status = "awaiting_review";
    review.stage = "awaiting_review";
    return structuredClone(review);
  },
  async confirmMeetingReview(workspaceId, sourceId, revision, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const review = state.reviews.get(sourceId);
    const job = [...state.jobs.values()].find((item) => item.sourceId === sourceId);
    if (!review || !job || !state.sources.some((item) => item.id === sourceId && item.workspaceId === workspaceId)) throw new ApiError(404, "검토 대본을 찾을 수 없습니다.");
    if (review.revision !== revision) throw new ApiError(409, "대본이 변경됐습니다. 다시 불러와 주세요.");
    if (review.reviewState === "confirmed") return advanceJob(job);
    if ((review.projectIds ?? []).some((id) => !state.projects.some((item) => item.id === id && item.workspaceId === workspaceId && !item.archivedAt)) || !review.utterances.some((item) => item.text.trim())) throw new ApiError(422, "활성 프로젝트와 발언을 확인해 주세요.");
    review.reviewState = "confirmed";
    review.status = "processing";
    review.stage = "analyzing";
    review.confirmedAt = new Date().toISOString();
    review.confirmedSnapshot = { projects: structuredClone(state.projects.filter((item) => (review.projectIds ?? []).includes(item.id))), people: structuredClone(state.people.filter((person) => review.utterances.some((item) => item.personId === person.id))) };
    job.status = "processing";
    job.stage = "analyzing";
    job.progress = 0;
    job.startedAt = Date.now();
    const source = state.sources.find((item) => item.id === sourceId);
    if (source) { source.status = "processing"; source.projectId = review.projectId; source.projectIds = review.projectIds ?? []; }
    return advanceJob(job);
  },

  async listContextItems(workspaceId, query, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    if (!state.workspaces.some((item) => item.id === workspaceId)) return [];

    let items: ContextItem[] = contextItems.map((item) => structuredClone(item));
    if (query?.kinds?.length) items = items.filter((item) => query.kinds!.includes(item.kind));
    if (query?.sourceKinds?.length) {
      items = items.filter((item) =>
        item.sources.some((source) => query.sourceKinds!.includes(source.kind)),
      );
    }
    if (query?.from) items = items.filter((item) => item.occurredAt >= query.from!);
    if (query?.to) items = items.filter((item) => item.occurredAt <= query.to!);

    return items.sort((a, b) => b.occurredAt.localeCompare(a.occurredAt));
  },

  async getContextStore(workspaceId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    if (!state.workspaces.some((item) => item.id === workspaceId)) return null;
    return structuredClone(contextStore);
  },

  async getKnowledgeGraph(workspaceId, query, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    if (!state.workspaces.some((item) => item.id === workspaceId)) {
      return { nodes: [], edges: [] };
    }

    // 실 API와 같은 규칙: 그 시점에 유효했던 관계만 남기고, 시작이나 종료를 모르면 열린 관계로 봅니다.
    // 노드는 시점으로 거르지 않으므로 연결 수만 다시 셉니다.
    const graph = structuredClone(knowledgeGraph);
    for (const person of state.people.filter((item) => item.workspaceId === workspaceId)) {
      const existing = graph.nodes.find((node) => node.id === person.id);
      if (existing) { existing.label = person.name; existing.directoryId = person.id; existing.directoryKind = "Person"; existing.kind = "Person"; }
      else graph.nodes.push({ id: person.id, directoryId: person.id, directoryKind: "Person", type: "person", kind: "Person", label: person.name, degree: 0, sources: [] });
    }
    for (const project of state.projects.filter((item) => item.workspaceId === workspaceId)) {
      const existing = graph.nodes.find((node) => node.id === project.id);
      if (existing) { existing.label = project.name; existing.directoryId = project.id; existing.directoryKind = "Project"; existing.kind = "Project"; }
      else graph.nodes.push({ id: project.id, directoryId: project.id, directoryKind: "Project", type: "project", kind: "Project", label: project.name, degree: 0, sources: [] });
      for (const personId of project.participantIds ?? []) graph.edges.push({ id: `member-${project.id}-${personId}`, source: personId, target: project.id, type: "relates_to", kind: "WORKS_ON", explicit: true });
    }
    if (query?.includeMaterials !== false) {
      for (const source of state.sources.filter((item) => item.workspaceId === workspaceId && item.status === "succeeded")) {
        const id = `material-${source.id}`;
        graph.nodes.push({ id, type: "event", kind: source.kind === "meeting" ? "Meeting" : "Document", label: source.title, degree: 0, sources: [], material: true, sourceId: source.id });
        for (const projectId of source.projectIds ?? []) graph.edges.push({ id: `material-project-${source.id}-${projectId}`, source: id, target: projectId, type: "relates_to", kind: "RELATED_TO", explicit: true, role: "project" });
        for (const association of source.associations ?? []) graph.edges.push({ id: `material-person-${source.id}-${association.personId}`, source: association.personId, target: id, type: association.role === "participant" ? "participates_in" : "relates_to", kind: association.role === "participant" ? "PARTICIPATED_IN" : "CREATED", explicit: true, role: association.role });
      }
    }
    const at = (query?.at ?? "9999-12-31").slice(0, 10);
    graph.edges = graph.edges.filter(
      (edge) =>
        (!edge.validFrom || edge.validFrom.slice(0, 10) <= at) &&
        (!edge.validTo || edge.validTo.slice(0, 10) >= at),
    );
    for (const node of graph.nodes) {
      node.degree = graph.edges.filter(
        (edge) => edge.source === node.id || edge.target === node.id,
      ).length;
    }
    return graph;
  },

  async *ask(_workspaceId, question, signal): AsyncGenerator<AnswerEvent, void, undefined> {
    await delay(MOCK_LATENCY_MS, signal);

    const matched = answers.find((answer) => answer.match.test(question));
    // 실제 서버와 같은 모양으로 끝냅니다: 근거가 없으면 모델을 부르지 않고 이 이벤트 하나만 보냅니다.
    if (!matched) {
      yield { type: "error", code: "no_evidence", message: fallbackAnswer.text };
      return;
    }
    yield { type: "sources", sources: matched.sources };

    // 실제 스트리밍처럼 보이도록 어절 단위로 흘려보냅니다.
    for (const word of matched.text.split(/(\s+)/)) {
      await delay(18, signal);
      yield { type: "token", text: word };
    }

    yield { type: "done" };
  },
};
