import { ApiError, apiFetch, apiPublicBlob, apiPublicFetch } from "./client";
import type { MaeglagiApi } from "./contract";
import { httpApi } from "./http";
import type { ContextItem, ContextStore, KnowledgeGraph, Source, SourceContent, Workspace, WorkspacePerson, WorkspaceProject } from "./types";

const loginRequired = () => { throw new ApiError(403, "데모는 읽기 전용입니다. 편집하려면 로그인해 내 워크스페이스에서 사용해 주세요."); };

/** Public demo data is read from the configured database workspace, never fixtures. */
export const demoHttpApi: MaeglagiApi = {
  ...httpApi,
  listMcpTokens: loginRequired,
  createMcpToken: loginRequired,
  extendMcpToken: loginRequired,
  revokeMcpToken: loginRequired,
  // This explicit write uses the authenticated client, unlike every public demo read below.
  cloneDemoWorkspace: (signal) => apiFetch<Workspace>("/demo/clone", { method: "POST", signal }),
  listWorkspaces: async (signal) => [await apiPublicFetch<Workspace>("/demo/workspace", { signal })],
  getWorkspace: (_id, signal) => apiPublicFetch<Workspace>("/demo/workspace", { signal }),
  listPeople: (_id, signal) => apiPublicFetch<WorkspacePerson[]>("/demo/people", { signal }),
  listProjects: (_id, signal) => apiPublicFetch<WorkspaceProject[]>("/demo/projects", { signal }),
  listProjectParticipants: async (_id, projectId, signal) => {
    const [people, projects] = await Promise.all([
      apiPublicFetch<WorkspacePerson[]>("/demo/people", { signal }),
      apiPublicFetch<WorkspaceProject[]>("/demo/projects", { signal }),
    ]);
    const ids = new Set(projects.find((item) => item.id === projectId)?.participantIds ?? []);
    return people.filter((person) => ids.has(person.id));
  },
  listSources: (_id, signal) => apiPublicFetch<Source[]>("/demo/sources", { signal }),
  getSourceContent: (id, signal) => apiPublicFetch<SourceContent>(`/demo/sources/${id}/content`, { signal }),
  getSourcePlaybackUrl: (id, signal) => apiPublicFetch<{ url: string; expiresAt: string }>(`/demo/sources/${id}/playback-url`, { signal }),
  exportSourceMarkdown: (id, signal) => apiPublicBlob(`/demo/sources/${id}/export.md`, { signal }),
  listContextItems: (_id, query, signal) => {
    const params = new URLSearchParams();
    for (const kind of query?.kinds ?? []) params.append("kind", kind);
    for (const kind of query?.sourceKinds ?? []) params.append("source_kind", kind);
    if (query?.from) params.set("from", query.from);
    if (query?.to) params.set("to", query.to);
    return apiPublicFetch<ContextItem[]>(`/demo/timeline${params.size ? `?${params}` : ""}`, { signal });
  },
  getContextStore: (_id, signal) => apiPublicFetch<ContextStore | null>("/demo/context-store", { signal }),
  getKnowledgeGraph: (_id, query, signal) => {
    const params = new URLSearchParams();
    if (query?.at) params.set("at", query.at);
    if (query?.includeMaterials !== undefined) params.set("includeMaterials", String(query.includeMaterials));
    return apiPublicFetch<KnowledgeGraph>(`/demo/graph${params.size ? `?${params}` : ""}`, { signal });
  },
  createWorkspace: loginRequired,
  updateApiKey: loginRequired,
  createAccountCredential: loginRequired,
  rotateAccountCredential: loginRequired,
  setDefaultAccountCredential: loginRequired,
  deleteAccountCredential: loginRequired,
  rotateProviderCredential: loginRequired,
  updateWorkspaceModels: loginRequired,
  createPerson: loginRequired,
  updatePerson: loginRequired,
  createProject: loginRequired,
  updateProject: loginRequired,
  setProjectParticipants: loginRequired,
  updateSourceAssociations: loginRequired,
  uploadDocument: loginRequired,
  uploadRecording: loginRequired,
  uploadTranscript: loginRequired,
  getMeetingReview: loginRequired,
  retryMeetingTranscription: loginRequired,
  submitBrowserTranscript: loginRequired,
  saveMeetingReview: loginRequired,
  confirmMeetingReview: loginRequired,
  async *ask() { throw new ApiError(403, "데모에서는 AI 질문을 실행하지 않습니다. 로그인해 내 워크스페이스에서 물어봐 주세요."); },
};
