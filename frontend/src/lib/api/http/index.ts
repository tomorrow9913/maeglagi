import { apiFetch, apiStream, apiUpload } from "../client";
import type { MaeglagiApi } from "../contract";
import type {
  AnswerEvent,
  AiProvider,
  ApiKeyValidation,
  ContextItem,
  ContextTimelineQuery,
  CreateWorkspaceInput,
  KnowledgeGraph,
  ProcessingJob,
  Source,
  SourceContent,
  Workspace,
  WorkspaceSecrets,
} from "../types";

function timelineQuery(query?: ContextTimelineQuery): string {
  if (!query) return "";

  const params = new URLSearchParams();
  for (const kind of query.kinds ?? []) params.append("kind", kind);
  for (const kind of query.sourceKinds ?? []) params.append("source_kind", kind);
  if (query.from) params.set("from", query.from);
  if (query.to) params.set("to", query.to);

  const search = params.toString();
  return search ? `?${search}` : "";
}

/** 실제 FastAPI 백엔드를 호출하는 구현입니다. */
export const httpApi: MaeglagiApi = {
  listWorkspaces: (signal) => apiFetch<Workspace[]>("/workspaces", { signal }),

  getWorkspace: (workspaceId, signal) =>
    apiFetch<Workspace>(`/workspaces/${workspaceId}`, { signal }),

  createWorkspace: (input: CreateWorkspaceInput, signal) =>
    apiFetch<Workspace>("/workspaces", {
      method: "POST",
      body: JSON.stringify(input),
      signal,
    }),

  listWorkspaceProviders: (workspaceId, signal) =>
    apiFetch<AiProvider[]>(`/workspaces/${workspaceId}/ai/providers`, { signal }),

  validateApiKey: (input, signal) =>
    apiFetch<ApiKeyValidation>("/llm-keys/validate", {
      method: "POST",
      body: JSON.stringify(input),
      signal,
    }),

  getWorkspaceSecrets: (workspaceId, signal) =>
    apiFetch<WorkspaceSecrets | null>(`/workspaces/${workspaceId}/llm-key`, { signal }),

  updateApiKey: (workspaceId, input, signal) =>
    apiFetch<WorkspaceSecrets>(`/workspaces/${workspaceId}/llm-key`, {
      method: "PUT",
      body: JSON.stringify(input),
      signal,
    }),

  listSources: (workspaceId, signal) =>
    apiFetch<Source[]>(`/workspaces/${workspaceId}/sources`, { signal }),

  getSourceContent: (sourceId, signal) =>
    apiFetch<SourceContent>(`/sources/${sourceId}/content`, { signal }),

  uploadDocument: (workspaceId, file, options) => {
    const form = new FormData();
    form.append("file", file);
    return apiUpload<ProcessingJob>(`/workspaces/${workspaceId}/sources/documents`, form, options);
  },

  uploadRecording: (workspaceId, audio, options) => {
    const form = new FormData();
    form.append("audio", audio, "recording.webm");
    return apiUpload<ProcessingJob>(`/workspaces/${workspaceId}/sources/recordings`, form, options);
  },

  getJob: (jobId, signal) => apiFetch<ProcessingJob>(`/jobs/${jobId}`, { signal }),

  listContextItems: (workspaceId, query, signal) =>
    apiFetch<ContextItem[]>(`/workspaces/${workspaceId}/context${timelineQuery(query)}`, {
      signal,
    }),

  getKnowledgeGraph: (workspaceId, signal) =>
    apiFetch<KnowledgeGraph>(`/workspaces/${workspaceId}/graph`, { signal }),

  ask(workspaceId, question, signal) {
    return apiStream(`/workspaces/${workspaceId}/ask`, {
      method: "POST",
      body: JSON.stringify({ question }),
      signal,
    }) as AsyncIterable<AnswerEvent>;
  },
};
