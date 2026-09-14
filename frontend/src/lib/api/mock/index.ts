import { ApiError, type UploadOptions } from "../client";
import { MOCK_LATENCY_MS } from "../config";
import type { MaeglagiApi } from "../contract";
import type { AnswerEvent, ContextItem, ProcessingJob, Source, Workspace } from "../types";
import {
  answers,
  contextItems,
  fallbackAnswer,
  knowledgeGraph,
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
};

let sequence = 0;
const nextId = (prefix: string) => `${prefix}-${++sequence}`;

/** 경과 시간으로 진행률과 단계를 계산합니다. */
function advanceJob(job: ProcessingJob & { startedAt: number }): ProcessingJob {
  const stages = stageSequence[job.sourceKind];
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

    // BYOK 키는 저장만 하고 어떤 응답에도 포함하지 않습니다.
    const workspace: Workspace = {
      id: nextId("ws"),
      name: input.name.trim(),
      createdAt: new Date().toISOString(),
      sourceCount: 0,
    };
    state.workspaces.push(workspace);
    return { ...workspace };
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
    return registerUpload(workspaceId, {
      id: nextId("src"),
      workspaceId,
      kind: "meeting",
      title: `회의 녹음 ${new Date().toLocaleString("ko-KR")}`,
      status: "processing",
      createdAt: new Date().toISOString(),
      // Blob에는 길이 정보가 없으므로 대략치로 둡니다. 실제 값은 STT가 채웁니다.
      durationSeconds: Math.round(audio.size / 16_000),
    });
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

    let items: ContextItem[] = contextItems.map((item) => ({ ...item }));
    if (query?.kinds?.length) items = items.filter((item) => query.kinds!.includes(item.kind));
    if (query?.from) items = items.filter((item) => item.occurredAt >= query.from!);
    if (query?.to) items = items.filter((item) => item.occurredAt <= query.to!);

    return items.sort((a, b) => b.occurredAt.localeCompare(a.occurredAt));
  },

  async getKnowledgeGraph(workspaceId, signal) {
    await delay(MOCK_LATENCY_MS, signal);
    if (!state.workspaces.some((item) => item.id === workspaceId)) {
      return { nodes: [], edges: [] };
    }
    return structuredClone(knowledgeGraph);
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
