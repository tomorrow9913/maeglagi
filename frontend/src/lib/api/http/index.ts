import { apiBlob, apiFetch, apiStream, apiUpload } from "../client";
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
  McpTokenList,
  CreatedMcpToken,
  ProcessingJob,
  MeetingReview,
  MeetingUtterance,
  PersonInput,
  ProjectInput,
  WorkspacePerson,
  WorkspaceProject,
  Source,
  SourceAssociations,
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
  listMcpTokens: (signal) => apiFetch<McpTokenList>("/mcp-tokens", { signal }),
  createMcpToken: (input, signal) =>
    apiFetch<CreatedMcpToken>("/mcp-tokens", {
      method: "POST",
      body: JSON.stringify(input),
      signal,
    }),
  revokeMcpToken: (tokenId, signal) =>
    apiFetch<void>(`/mcp-tokens/${encodeURIComponent(tokenId)}`, { method: "DELETE", signal }),
  listWorkspaces: (signal) => apiFetch<Workspace[]>("/workspaces", { signal }),

  getWorkspace: (workspaceId, signal) =>
    apiFetch<Workspace>(`/workspaces/${workspaceId}`, { signal }),

  createWorkspace: (input: CreateWorkspaceInput, signal) =>
    apiFetch<Workspace>("/workspaces", {
      method: "POST",
      body: JSON.stringify(input),
      signal,
    }),

  cloneDemoWorkspace: (signal) =>
    apiFetch<Workspace>("/demo/clone", { method: "POST", signal }),

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

  listAccountCredentials: (signal) =>
    apiFetch<WorkspaceSecrets[]>("/provider-credentials", { signal }),

  createAccountCredential: (input, signal) =>
    apiFetch<WorkspaceSecrets>("/provider-credentials", {
      method: "POST",
      body: JSON.stringify(input),
      signal,
    }),

  rotateAccountCredential: (credentialId, input, signal) =>
    apiFetch<WorkspaceSecrets>(`/provider-credentials/${credentialId}`, {
      method: "PUT",
      body: JSON.stringify(input),
      signal,
    }),

  setDefaultAccountCredential: (credentialId, signal) =>
    apiFetch<WorkspaceSecrets>(`/provider-credentials/${credentialId}/default`, {
      method: "PUT",
      signal,
    }),

  deleteAccountCredential: (credentialId, signal) =>
    apiFetch<void>(`/provider-credentials/${credentialId}`, { method: "DELETE", signal }),

  updateApiKey: (workspaceId, input, signal) =>
    apiFetch<WorkspaceSecrets>(`/workspaces/${workspaceId}/llm-key`, {
      method: "PUT",
      body: JSON.stringify(input),
      signal,
    }),

  rotateProviderCredential: (workspaceId, credentialId, input, signal) =>
    apiFetch<WorkspaceSecrets>(`/workspaces/${workspaceId}/provider-credentials/${credentialId}`, {
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
  listProjectParticipants: (workspaceId, projectId, signal) => apiFetch<WorkspacePerson[]>(`/workspaces/${workspaceId}/projects/${projectId}/participants`, { signal }),
  setProjectParticipants: (workspaceId, projectId, input, signal) => apiFetch<WorkspaceProject>(`/workspaces/${workspaceId}/projects/${projectId}/participants`, { method: "PUT", body: JSON.stringify(input), signal }),

  listSources: (workspaceId, signal) =>
    apiFetch<Source[]>(`/workspaces/${workspaceId}/sources`, { signal }),

  getSourceContent: (sourceId, signal) =>
    apiFetch<SourceContent>(`/sources/${sourceId}/content`, { signal }),
  getSourcePlaybackUrl: (sourceId, signal) => apiFetch<{ url: string; expiresAt: string }>(`/sources/${sourceId}/playback-url`, { method: "POST", signal }),
  exportSourceMarkdown: (sourceId, signal) => apiBlob(`/sources/${sourceId}/export.md`, { signal }),
  updateSourceAssociations: (workspaceId, sourceId, input, signal) => apiFetch<SourceAssociations>(`/workspaces/${workspaceId}/sources/${sourceId}/associations`, { method: "PATCH", body: JSON.stringify(input), signal }),

  uploadDocument: (workspaceId, file, options) => {
    const form = new FormData();
    form.append("file", file);
    return apiUpload<ProcessingJob>(`/workspaces/${workspaceId}/sources/documents`, form, options);
  },

  uploadRecording: (workspaceId, audio, liveDraft?: { utterances: MeetingUtterance[] }, projectId?, options?) => {
    const form = new FormData();
    form.append("audio", audio, typeof File !== "undefined" && audio instanceof File ? audio.name : "recording.webm");
    if (liveDraft?.utterances.length) form.append("liveDraft", JSON.stringify(liveDraft));
    if (projectId) form.append("projectId", projectId);
    if (options?.projectIds) form.append("projectIds", JSON.stringify(options.projectIds));
    return apiUpload<ProcessingJob>(`/workspaces/${workspaceId}/sources/recordings`, form, options);
  },

  uploadTranscript: (workspaceId, input: TranscriptSourceInput, signal) =>
    apiFetch<ProcessingJob>(`/workspaces/${workspaceId}/sources/transcripts`, {
      method: "POST",
      body: JSON.stringify(input),
      signal,
    }),

  getJob: (jobId, signal) => apiFetch<ProcessingJob>(`/jobs/${jobId}`, { signal }),
  sourceEvents(workspaceId, sourceIds, signal) {
    const ids = sourceIds.slice(0, 100).join(",");
    return apiStream(`/workspaces/${workspaceId}/source-events?source_ids=${encodeURIComponent(ids)}`, { signal }) as AsyncIterable<ProcessingJob>;
  },
  getMeetingReview: (workspaceId, sourceId, signal) => apiFetch<MeetingReview>(`/workspaces/${workspaceId}/sources/${sourceId}/review`, { signal }),
  retryMeetingTranscription: (workspaceId, sourceId, signal) => apiFetch<ProcessingJob>(`/workspaces/${workspaceId}/sources/${sourceId}/review/retry-transcription`, { method: "POST", signal }),
  submitBrowserTranscript: (workspaceId, sourceId, input, signal) => apiFetch<MeetingReview>(`/workspaces/${workspaceId}/sources/${sourceId}/review/browser-transcript`, { method: "POST", body: JSON.stringify(input), signal }),
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
    if (query?.includeMaterials !== undefined) params.set("includeMaterials", String(query.includeMaterials));
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
