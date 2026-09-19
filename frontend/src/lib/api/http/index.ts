import { apiFetch, apiStream, apiUpload } from "../client";
import type { MaeglagiApi } from "../contract";
import type {
  AnswerEvent,
  AiProvider,
  ApiKeyValidation,
  ContextItem,
  ContextStore,
  ContextTimelineQuery,
  CreateWorkspaceInput,
  KnowledgeGraph,
  ProcessingJob,
  MeetingReview,
  MeetingUtterance,
  PersonInput,
  ProjectInput,
  WorkspacePerson,
  WorkspaceProject,
  Source,
  SourceContent,
  TranscriptSourceInput,
  Workspace,
  WorkspaceModels,
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

  listProviders: (signal) => apiFetch<AiProvider[]>("/ai/providers", { signal }),

  listWorkspaceProviders: (workspaceId, signal) =>
    apiFetch<AiProvider[]>(`/workspaces/${workspaceId}/ai/providers`, { signal }),

  validateApiKey: (input, signal) =>
    apiFetch<ApiKeyValidation>("/llm-keys/validate", {
      method: "POST",
      body: JSON.stringify(input),
      signal,
    }),

  listKeyModels: (input, signal) =>
    apiFetch<WorkspaceModels>("/llm-keys/models", {
      method: "POST",
      body: JSON.stringify(input),
      signal,
    }),

  getWorkspaceModels: (workspaceId, provider, signal) =>
    apiFetch<WorkspaceModels>(
      `/workspaces/${workspaceId}/ai/models${provider ? `?provider=${encodeURIComponent(provider)}` : ""}`,
      { signal },
    ),

  updateWorkspaceModels: (workspaceId, selections, signal) =>
    apiFetch<WorkspaceModels>(`/workspaces/${workspaceId}/ai/models`, {
      method: "PUT",
      body: JSON.stringify({ selections }),
      signal,
    }),

  getWorkspaceSecrets: (workspaceId, signal) =>
    apiFetch<WorkspaceSecrets | null>(`/workspaces/${workspaceId}/llm-key`, { signal }),

  listProviderCredentials: (workspaceId, signal) =>
    apiFetch<WorkspaceSecrets[]>(`/workspaces/${workspaceId}/provider-credentials`, { signal }),

  updateApiKey: (workspaceId, input, signal) =>
    apiFetch<WorkspaceSecrets>(`/workspaces/${workspaceId}/llm-key`, {
      method: "PUT",
      body: JSON.stringify(input),
      signal,
    }),

  listPeople: (workspaceId, signal) => apiFetch<WorkspacePerson[]>(`/workspaces/${workspaceId}/people`, { signal }),
  createPerson: (workspaceId, input: PersonInput, signal) => apiFetch<WorkspacePerson>(`/workspaces/${workspaceId}/people`, { method: "POST", body: JSON.stringify(input), signal }),
  updatePerson: (workspaceId, personId, input, signal) => apiFetch<WorkspacePerson>(`/workspaces/${workspaceId}/people/${personId}`, { method: "PATCH", body: JSON.stringify(input), signal }),
  listProjects: (workspaceId, signal) => apiFetch<WorkspaceProject[]>(`/workspaces/${workspaceId}/projects`, { signal }),
  createProject: (workspaceId, input: ProjectInput, signal) => apiFetch<WorkspaceProject>(`/workspaces/${workspaceId}/projects`, { method: "POST", body: JSON.stringify(input), signal }),
  updateProject: (workspaceId, projectId, input, signal) => apiFetch<WorkspaceProject>(`/workspaces/${workspaceId}/projects/${projectId}`, { method: "PATCH", body: JSON.stringify(input), signal }),

  listSources: (workspaceId, signal) =>
    apiFetch<Source[]>(`/workspaces/${workspaceId}/sources`, { signal }),

  getSourceContent: (sourceId, signal) =>
    apiFetch<SourceContent>(`/sources/${sourceId}/content`, { signal }),

  uploadDocument: (workspaceId, file, options) => {
    const form = new FormData();
    form.append("file", file);
    return apiUpload<ProcessingJob>(`/workspaces/${workspaceId}/sources/documents`, form, options);
  },

  uploadRecording: (workspaceId, audio, liveDraft?: { utterances: MeetingUtterance[] }, projectId?, options?) => {
    const form = new FormData();
    form.append("audio", audio, "recording.webm");
    if (liveDraft?.utterances.length) form.append("liveDraft", JSON.stringify(liveDraft));
    if (projectId) form.append("projectId", projectId);
    return apiUpload<ProcessingJob>(`/workspaces/${workspaceId}/sources/recordings`, form, options);
  },

  uploadTranscript: (workspaceId, input: TranscriptSourceInput, signal) =>
    apiFetch<ProcessingJob>(`/workspaces/${workspaceId}/sources/transcripts`, {
      method: "POST",
      body: JSON.stringify(input),
      signal,
    }),

  getJob: (jobId, signal) => apiFetch<ProcessingJob>(`/jobs/${jobId}`, { signal }),
  getMeetingReview: (workspaceId, sourceId, signal) => apiFetch<MeetingReview>(`/workspaces/${workspaceId}/sources/${sourceId}/review`, { signal }),
  saveMeetingReview: (workspaceId, sourceId, input, signal) => apiFetch<MeetingReview>(`/workspaces/${workspaceId}/sources/${sourceId}/review`, { method: "PATCH", body: JSON.stringify(input), signal }),
  confirmMeetingReview: (workspaceId, sourceId, revision, signal) => apiFetch<ProcessingJob>(`/workspaces/${workspaceId}/sources/${sourceId}/review/confirm`, { method: "POST", body: JSON.stringify({ revision }), signal }),

  listContextItems: (workspaceId, query, signal) =>
    apiFetch<ContextItem[]>(`/workspaces/${workspaceId}/context${timelineQuery(query)}`, {
      signal,
    }),

  getContextStore: (workspaceId, signal) =>
    apiFetch<ContextStore | null>(`/workspaces/${workspaceId}/context-store`, { signal }),

  getKnowledgeGraph: (workspaceId, query, signal) => {
    const params = new URLSearchParams();
    if (query?.at) params.set("at", query.at);
    const search = params.toString();
    return apiFetch<KnowledgeGraph>(
      `/workspaces/${workspaceId}/graph${search ? `?${search}` : ""}`,
      {
        signal,
      },
    );
  },

  ask(workspaceId, question, signal) {
    return apiStream(`/workspaces/${workspaceId}/ask`, {
      method: "POST",
      body: JSON.stringify({ question }),
      signal,
    }) as AsyncIterable<AnswerEvent>;
  },
};
