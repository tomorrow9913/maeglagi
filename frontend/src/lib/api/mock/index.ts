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
  Source,
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
  workspaces: [...seedWorkspaces],
  sources: [...seedSources],
  jobs: new Map<string, ProcessingJob & { startedAt: number }>(),
  /** 키 원문은 저장하지 않고, 서버가 내려줄 힌트만 흉내 냅니다. */
  secrets: new Map<string, WorkspaceSecrets>([
    ["demo", { provider: "anthropic", keyHint: "4f2a", updatedAt: "2026-09-08T09:00:00Z" }],
  ]),
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
  const catalog = modelCatalog[provider] ?? {};
  return {
    roles: MODEL_ROLES.map((role) => ({
      role,
      options: (catalog[role] ?? []).map((model) => ({ provider, model })),
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
function checkApiKey(provider: LlmProvider, apiKey: string): ApiKeyValidation {
  const key = apiKey.trim();

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

function storeKey(workspaceId: string, provider: LlmProvider, apiKey: string): WorkspaceSecrets {
  const secrets: WorkspaceSecrets = {
    provider,
    keyHint: apiKey.trim().slice(-4),
    updatedAt: new Date().toISOString(),
  };
  state.secrets.set(workspaceId, secrets);
  return secrets;
}

let sequence = 0;
const nextId = (prefix: string) => `${prefix}-${++sequence}`;

/** 경과 시간으로 진행률과 단계를 계산합니다. */
function advanceJob(job: ProcessingJob & { startedAt: number }): ProcessingJob {
  const stages =
    job.transcriptSource === "browser"
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
    id: nextId("job"),
    sourceId: source.id,
    sourceKind: source.kind,
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
    if (!input.llmApiKey.trim()) throw new ApiError(422, "API key를 입력해 주세요.");

    const check = checkApiKey(input.llmProvider, input.llmApiKey);
    if (!check.valid) throw new ApiError(422, check.message);

    const workspace: Workspace = {
      id: nextId("ws"),
      name: input.name.trim(),
      createdAt: new Date().toISOString(),
      sourceCount: 0,
    };
    state.workspaces.push(workspace);

    // BYOK 키는 저장만 하고 어떤 응답에도 포함하지 않습니다.
    storeKey(workspace.id, input.llmProvider, input.llmApiKey);
    if (input.models) state.models.set(workspace.id, { ...input.models });
    return { ...workspace };
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

    const configuredProvider = state.secrets.get(workspaceId)?.provider;
    return BOOTSTRAP_AI_PROVIDERS.map<AiProvider>((provider) => ({
      ...provider,
      capabilities: [...provider.capabilities],
      configured: provider.id === configuredProvider,
      models:
        provider.id === configuredProvider
          ? provider.id === "anthropic"
            ? ["claude-sonnet-4-20250514"]
            : provider.id === "nvidia"
              ? ["meta/llama-3.1-70b-instruct"]
              : ["gpt-4.1-mini"]
          : [],
    }));
  },

  async validateApiKey(input, signal) {
    // 실제 provider 호출을 흉내 내느라 조금 더 걸립니다.
    await delay(MOCK_LATENCY_MS * 2, signal);
    return checkApiKey(input.provider, input.apiKey);
  },

  async listKeyModels(input, signal) {
    await delay(MOCK_LATENCY_MS * 2, signal);
    const check = checkApiKey(input.provider, input.apiKey);
    if (!check.valid) throw new ApiError(422, check.message);
    return modelsFor(input.provider);
  },

  async getWorkspaceModels(workspaceId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const secrets = state.secrets.get(workspaceId);
    if (!state.workspaces.some((item) => item.id === workspaceId) || !secrets) {
      throw new ApiError(404, "워크스페이스를 찾을 수 없습니다.");
    }
    return modelsFor(secrets.provider, state.models.get(workspaceId), lockedRoles(workspaceId));
  },

  async updateWorkspaceModels(workspaceId, selections, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const secrets = state.secrets.get(workspaceId);
    if (!state.workspaces.some((item) => item.id === workspaceId) || !secrets) {
      throw new ApiError(404, "워크스페이스를 찾을 수 없습니다.");
    }

    const current = modelsFor(
      secrets.provider,
      state.models.get(workspaceId),
      lockedRoles(workspaceId),
    );
    const next: ModelSelections = { ...state.models.get(workspaceId) };
    for (const role of MODEL_ROLES) {
      const wanted = selections[role];
      if (!wanted) continue;
      const entry = current.roles.find((item) => item.role === role)!;
      if (!entry.options.some((o) => o.provider === wanted.provider && o.model === wanted.model)) {
        throw new ApiError(422, `${wanted.model}은(는) 이 키로 쓸 수 있는 모델이 아닙니다.`);
      }
      const unchanged =
        entry.selected?.provider === wanted.provider && entry.selected.model === wanted.model;
      if (entry.locked && !unchanged) {
        throw new ApiError(409, "임베딩 모델은 워크스페이스를 만들 때 정해지며 바꿀 수 없습니다.");
      }
      next[role] = wanted;
    }
    state.models.set(workspaceId, next);
    return modelsFor(secrets.provider, next, lockedRoles(workspaceId));
  },

  async getWorkspaceSecrets(workspaceId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    return state.secrets.get(workspaceId) ?? null;
  },

  async updateApiKey(workspaceId, input, signal) {
    await delay(MOCK_LATENCY_MS * 2, signal);
    if (!state.workspaces.some((item) => item.id === workspaceId)) {
      throw new ApiError(404, "워크스페이스를 찾을 수 없습니다.");
    }

    const check = checkApiKey(input.provider, input.apiKey);
    if (!check.valid) throw new ApiError(422, check.message);

    return storeKey(workspaceId, input.provider, input.apiKey);
  },

  async listSources(workspaceId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    return state.sources
      .filter((source) => source.workspaceId === workspaceId)
      .map((source) => ({ ...source }));
  },

  async getSourceContent(sourceId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    const content = sourceContents.find((item) => item.sourceId === sourceId);
    if (!content) throw new ApiError(404, "원문을 찾을 수 없습니다.");
    return structuredClone(content);
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

  async uploadRecording(workspaceId, audio, options) {
    await simulateTransfer(options);
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
    });
    job.transcriptSource = "server";
    return job;
  },

  async uploadTranscript(workspaceId, input, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    if (!input.text.trim()) throw new ApiError(422, "대본을 입력해 주세요.");
    const job = registerUpload(workspaceId, {
      id: nextId("src"),
      workspaceId,
      kind: "meeting",
      title: input.title?.trim() || `회의 대본 ${new Date().toLocaleString("ko-KR")}`,
      status: "processing",
      createdAt: new Date().toISOString(),
      durationSeconds: input.durationSeconds,
      transcriptSource: "browser",
    });
    job.transcriptSource = "browser";
    return job;
  },

  async getJob(jobId, signal) {
    await delay(120, signal);
    const job = state.jobs.get(jobId);
    if (!job) throw new ApiError(404, "처리 작업을 찾을 수 없습니다.");
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

    const matched = answers.find((answer) => answer.match.test(question)) ?? fallbackAnswer;
    yield { type: "sources", sources: matched.sources };

    // 실제 스트리밍처럼 보이도록 어절 단위로 흘려보냅니다.
    for (const word of matched.text.split(/(\s+)/)) {
      await delay(18, signal);
      yield { type: "token", text: word };
    }

    yield { type: "done" };
  },
};
