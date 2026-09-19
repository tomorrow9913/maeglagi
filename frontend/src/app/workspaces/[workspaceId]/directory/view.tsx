"use client";

import { use, useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { ChevronDown, UserPlus } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/page-header";
import { DemoAuthGuidance } from "@/components/layout/demo-auth-guidance";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useApi, useDemoMode, useWorkspacePath } from "@/lib/api/context";
import type { KnowledgeGraph, WorkspacePerson, WorkspaceProject } from "@/lib/api";
import { buildPersonContext, type PersonActivity } from "@/features/directory/lib/person-context";
import { listProjectPeople } from "@/features/directory/lib/project-people";

type PersonForm = { name: string; email: string; aliases: string; role: string };
type ProjectForm = {
  name: string;
  goal: string;
  description: string;
  ownerPersonId: string;
  participantIds: string[];
  startsOn: string;
  endsOn: string;
};
const emptyPerson: PersonForm = { name: "", email: "", aliases: "", role: "" };
const emptyProject: ProjectForm = {
  name: "",
  goal: "",
  description: "",
  ownerPersonId: "",
  participantIds: [],
  startsOn: "",
  endsOn: "",
};
function errorText(error: unknown) {
  return error instanceof Error ? error.message : "요청을 완료하지 못했습니다.";
}
function ActivityList({
  items,
  empty,
  workspaceId,
}: {
  items: PersonActivity[];
  empty: string;
  workspaceId: string;
}) {
  const workspacePath = useWorkspacePath();
  if (!items.length) return <p className="text-muted-foreground">{empty}</p>;
  return (
    <ul className="space-y-2">
      {items.map((item) => (
        <li key={item.node.id} className="rounded-md border p-2">
          <p className="font-medium">{item.node.label}</p>
          {item.node.type === "decision" && item.node.supersededBy && (
            <p className="text-xs text-muted-foreground">대체된 결정</p>
          )}
          <p className="text-xs text-muted-foreground">
            {item.relation}
            {item.via ? ` · ${item.via.label} 경유` : ""}
          </p>
          {item.node.sources.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-2">
              {item.node.sources.map((source) => (
                <Link
                  key={source.id}
                  href={`${workspacePath(workspaceId, "sources")}?source=${encodeURIComponent(source.id)}${source.chunkId ? `&chunk=${encodeURIComponent(source.chunkId)}` : ""}`}
                  className="text-xs underline underline-offset-2"
                >
                  {source.title}
                </Link>
              ))}
            </div>
          )}
          {item.decisions?.length ? (
            <div className="mt-2 border-l pl-2">
              <p className="text-xs font-medium">연결된 결정</p>
              {item.decisions.map((decision) => (
                <p key={decision.node.id} className="text-xs">
                  {decision.node.label}
                  {decision.node.supersededBy && (
                    <span className="ml-2 text-muted-foreground">대체된 결정</span>
                  )}
                </p>
              ))}
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

export default function DirectoryPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  return <DirectoryView workspaceId={workspaceId} />;
}

export function DirectoryView({ workspaceId }: { workspaceId: string }) {
  const api = useApi();
  const isDemo = useDemoMode();
  const [people, setPeople] = useState<WorkspacePerson[]>([]);
  const [projects, setProjects] = useState<WorkspaceProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadedWorkspaceId, setLoadedWorkspaceId] = useState<string>();
  const [loadError, setLoadError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [expanded, setExpanded] = useState<string[]>([]);
  const [unassignedOpen, setUnassignedOpen] = useState(false);
  const [projectDialog, setProjectDialog] = useState<"create" | "edit" | null>(null);
  const createdProjectRef = useRef<string | undefined>(undefined);
  const [personId, setPersonId] = useState<string>();
  const [addProjectId, setAddProjectId] = useState<string>();
  const [personEditing, setPersonEditing] = useState(false);
  const [personForm, setPersonForm] = useState<PersonForm>(emptyPerson);
  const [projectForm, setProjectForm] = useState<ProjectForm>(emptyProject);
  const [editingProjectId, setEditingProjectId] = useState<string>();
  const [selectedPersonId, setSelectedPersonId] = useState("");
  const [newPerson, setNewPerson] = useState<PersonForm>(emptyPerson);
  const [addMode, setAddMode] = useState<"existing" | "new">("existing");
  const createdPersonRef = useRef<string | undefined>(undefined);
  const [createdPersonId, setCreatedPersonId] = useState<string>();
  const [graph, setGraph] = useState<KnowledgeGraph | null>(null);
  const [graphStatus, setGraphStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [graphError, setGraphError] = useState<string>();
  const [graphRetry, setGraphRetry] = useState(0);
  const graphCacheRef = useRef<
    { api: typeof api; workspaceId: string; graph: KnowledgeGraph } | undefined
  >(undefined);
  const graphRequestRef = useRef<AbortController | null>(null);
  const graphRequestId = useRef(0);
  const initialLinkHandled = useRef(false);

  const invalidateGraph = useCallback(() => {
    graphCacheRef.current = undefined;
    graphRequestRef.current?.abort();
    graphRequestRef.current = null;
    graphRequestId.current += 1;
    setGraph(null);
    setGraphStatus("idle");
    setGraphRetry((value) => value + 1);
  }, []);
  useEffect(() => {
    graphCacheRef.current = undefined;
    graphRequestRef.current?.abort();
    graphRequestRef.current = null;
    graphRequestId.current += 1;
    setGraph(null);
    setGraphStatus("idle");
  }, [api, workspaceId]);

  const reload = useCallback(async () => {
    const [nextPeople, nextProjects] = await Promise.all([
      api.listPeople(workspaceId),
      api.listProjects(workspaceId),
    ]);
    setPeople(nextPeople);
    setProjects(nextProjects);
    setLoadedWorkspaceId(workspaceId);
    setLoadError(undefined);
    return { nextPeople, nextProjects };
  }, [api, workspaceId]);
  useEffect(() => {
    let live = true;
    setLoading(true);
    setLoadError(undefined);
    Promise.all([api.listPeople(workspaceId), api.listProjects(workspaceId)])
      .then(([nextPeople, nextProjects]) => {
        if (!live) return;
        setPeople(nextPeople);
        setProjects(nextProjects);
        setLoadedWorkspaceId(workspaceId);
        setLoading(false);
      })
      .catch((error) => {
        if (live) {
          setLoadError(errorText(error));
          setLoading(false);
        }
      });
    return () => {
      live = false;
    };
  }, [api, workspaceId]);
  useEffect(() => {
    initialLinkHandled.current = false;
    setPersonId(undefined);
    setProjectDialog(null);
    setAddProjectId(undefined);
  }, [workspaceId]);
  useEffect(() => {
    if (loading || loadError || loadedWorkspaceId !== workspaceId || initialLinkHandled.current)
      return;
    initialLinkHandled.current = true;
    const query = new URLSearchParams(window.location.search);
    const linkedPerson = people.find((item) => item.id === query.get("person"));
    const linkedProject = projects.find((item) => item.id === query.get("project"));
    if (linkedPerson) {
      setPersonId(linkedPerson.id);
      setPersonForm({
        name: linkedPerson.name,
        email: linkedPerson.email ?? "",
        aliases: linkedPerson.aliases.join(", "),
        role: linkedPerson.role ?? "",
      });
    } else if (linkedProject)
      setExpanded((current) =>
        current.includes(linkedProject.id) ? current : [...current, linkedProject.id],
      );
  }, [loading, loadError, loadedWorkspaceId, workspaceId, people, projects]);
  useEffect(() => {
    const onPopState = () => {
      const query = new URLSearchParams(window.location.search);
      const linkedPerson = people.find((item) => item.id === query.get("person"));
      setPersonId(linkedPerson?.id);
      if (linkedPerson)
        setPersonForm({
          name: linkedPerson.name,
          email: linkedPerson.email ?? "",
          aliases: linkedPerson.aliases.join(", "),
          role: linkedPerson.role ?? "",
        });
      const project = projects.find((item) => item.id === query.get("project"));
      if (project)
        setExpanded((current) =>
          current.includes(project.id) ? current : [...current, project.id],
        );
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [people, projects]);
  useEffect(() => {
    if (!personId || loadedWorkspaceId !== workspaceId) {
      setGraph(null);
      setGraphStatus("idle");
      return;
    }
    const cached = graphCacheRef.current;
    if (cached?.api === api && cached.workspaceId === workspaceId) {
      setGraph(cached.graph);
      setGraphError(undefined);
      setGraphStatus("ready");
      return;
    }
    const controller = new AbortController();
    graphRequestRef.current = controller;
    const requestId = ++graphRequestId.current;
    setGraphStatus("loading");
    setGraphError(undefined);
    setGraph(null);
    api
      .getKnowledgeGraph(workspaceId, { includeMaterials: true }, controller.signal)
      .then((next) => {
        if (!controller.signal.aborted && requestId === graphRequestId.current) {
          graphCacheRef.current = { api, workspaceId, graph: next };
          setGraph(next);
          setGraphStatus("ready");
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted && requestId === graphRequestId.current) {
          setGraphError(errorText(error));
          setGraphStatus("error");
        }
      })
      .finally(() => {
        if (graphRequestRef.current === controller) graphRequestRef.current = null;
      });
    return () => controller.abort();
  }, [api, workspaceId, loadedWorkspaceId, personId, graphRetry]);
  const setLink = (kind?: "person" | "project", id?: string) => {
    const url = new URL(window.location.href);
    url.searchParams.delete("person");
    url.searchParams.delete("project");
    if (kind && id) url.searchParams.set(kind, id);
    window.history.replaceState(null, "", url);
  };
  const act = async (action: () => Promise<void>, onSuccess?: () => void) => {
    if (busyRef.current || isDemo) return;
    busyRef.current = true;
    setBusy(true);
    try {
      await action();
      await reload();
      onSuccess?.();
      toast.success("저장했습니다.");
    } catch (error) {
      toast.error(errorText(error));
      await reload().catch(() => undefined);
    } finally {
      invalidateGraph();
      busyRef.current = false;
      setBusy(false);
    }
  };
  const openPerson = (person: WorkspacePerson) => {
    setPersonId(person.id);
    setPersonEditing(false);
    setPersonForm({
      name: person.name,
      email: person.email ?? "",
      aliases: person.aliases.join(", "),
      role: person.role ?? "",
    });
    setLink("person", person.id);
  };
  const closePerson = () => {
    setPersonId(undefined);
    setPersonEditing(false);
    setLink();
  };
  const openProject = (project: WorkspaceProject) => {
    const isOpen = expanded.includes(project.id);
    setExpanded((current) =>
      isOpen ? current.filter((id) => id !== project.id) : [...current, project.id],
    );
    if (isOpen) setLink();
    else setLink("project", project.id);
  };
  const openProjectEditor = (project?: WorkspaceProject) => {
    createdProjectRef.current = undefined;
    setEditingProjectId(project?.id);
    setProjectForm(
      project
        ? {
            name: project.name,
            goal: project.goal ?? "",
            description: project.description ?? "",
            ownerPersonId: project.ownerPersonId ?? "",
            participantIds: project.participantIds ?? [],
            startsOn: project.startsOn ?? "",
            endsOn: project.endsOn ?? "",
          }
        : emptyProject,
    );
    setProjectDialog(project ? "edit" : "create");
  };
  const closeProjectEditor = () => {
    createdProjectRef.current = undefined;
    setEditingProjectId(undefined);
    setProjectDialog(null);
  };
  const openAdd = (project: WorkspaceProject) => {
    setAddProjectId(project.id);
    setSelectedPersonId("");
    setNewPerson(emptyPerson);
    setCreatedPersonId(undefined);
    createdPersonRef.current = undefined;
    setAddMode("existing");
  };
  const closeAdd = () => {
    setAddProjectId(undefined);
    setCreatedPersonId(undefined);
    createdPersonRef.current = undefined;
  };
  const submitProject = (event: FormEvent) => {
    event.preventDefault();
    const input = {
      name: projectForm.name.trim(),
      goal: projectForm.goal.trim() || null,
      description: projectForm.description.trim() || null,
      ownerPersonId: projectForm.ownerPersonId || null,
      startsOn: projectForm.startsOn || null,
      endsOn: projectForm.endsOn || null,
    };
    void act(async () => {
      const projectId = editingProjectId ?? createdProjectRef.current;
      const project = projectId
        ? await api.updateProject(workspaceId, projectId, input)
        : await api.createProject(workspaceId, input);
      if (!projectId) {
        createdProjectRef.current = project.id;
        setEditingProjectId(project.id);
        setProjectDialog("edit");
      } else {
        const previous = new Set(project.participantIds ?? []);
        const next = new Set(projectForm.participantIds);
        if (previous.size !== next.size || [...next].some((id) => !previous.has(id)))
          await api.setProjectParticipants(workspaceId, project.id, {
            revision: project.revision ?? 0,
            personIds: [...next],
          });
      }
    }, closeProjectEditor);
  };
  const submitPerson = (event: FormEvent) => {
    event.preventDefault();
    if (!personId) return;
    const input = {
      name: personForm.name.trim(),
      email: personForm.email.trim() || null,
      aliases: personForm.aliases
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
      role: personForm.role.trim() || null,
    };
    void act(
      () => api.updatePerson(workspaceId, personId, input).then(() => undefined),
      () => setPersonEditing(false),
    );
  };
  const submitAdd = (event: FormEvent) => {
    event.preventDefault();
    const projectId = addProjectId;
    if (!projectId) return;
    void act(async () => {
      let id = selectedPersonId;
      if (addMode === "new") {
        if (!createdPersonRef.current) {
          const person = await api.createPerson(workspaceId, {
            name: newPerson.name.trim(),
            email: newPerson.email.trim(),
            aliases: [],
            role: null,
          });
          createdPersonRef.current = person.id;
          setCreatedPersonId(person.id);
        }
        id = createdPersonRef.current;
      }
      // Fetch current revision immediately before changing the participant set.
      const current = (await api.listProjects(workspaceId)).find((item) => item.id === projectId);
      if (!current) throw new Error("프로젝트를 찾을 수 없습니다.");
      if (current.participantIds?.includes(id)) return;
      await api.setProjectParticipants(workspaceId, projectId, {
        revision: current.revision ?? 0,
        personIds: [...(current.participantIds ?? []), id],
      });
    }, closeAdd);
  };
  const person =
    loadedWorkspaceId === workspaceId ? people.find((item) => item.id === personId) : undefined;
  const personContext = person
    ? buildPersonContext(person, projects, graphStatus === "ready" ? graph : null)
    : null;
  const addProject =
    loadedWorkspaceId === workspaceId
      ? projects.find((item) => item.id === addProjectId)
      : undefined;
  const assigned = new Set(
    projects
      .flatMap((item) => item.participantIds ?? [])
      .concat(projects.map((item) => item.ownerPersonId).filter((id): id is string => Boolean(id))),
  );
  const unassigned = people.filter((item) => !assigned.has(item.id));
  const selectedOwner = people.find((item) => item.id === projectForm.ownerPersonId);
  const invalidOwner = Boolean(
    projectForm.ownerPersonId && (!selectedOwner || selectedOwner.archivedAt),
  );
  const availablePeople = people.filter(
    (item) => !item.archivedAt && !(addProject?.participantIds ?? []).includes(item.id),
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="프로젝트와 참여자"
        description={
          isDemo
            ? "공개 데모의 실제 워크스페이스 데이터를 읽기 전용으로 살펴봅니다."
            : "프로젝트를 열어 참여자와 업무 맥락을 살펴봅니다."
        }
      />
      {isDemo && <DemoAuthGuidance />}
      {loading || (loadedWorkspaceId !== workspaceId && !loadError) ? (
        <p role="status" className="text-sm text-muted-foreground">
          목록을 불러오는 중입니다.
        </p>
      ) : loadError ? (
        <div role="alert" className="space-y-2">
          <p className="text-sm text-destructive">{loadError}</p>
          <Button
            variant="outline"
            onClick={() => {
              setLoading(true);
              void reload()
                .catch((error) => setLoadError(errorText(error)))
                .finally(() => setLoading(false));
            }}
          >
            다시 시도
          </Button>
        </div>
      ) : (
        <>
          <section aria-labelledby="projects-heading" className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 id="projects-heading" className="text-lg font-semibold">
                프로젝트
              </h2>
              {!isDemo && (
                <Button type="button" onClick={() => openProjectEditor()}>
                  새 프로젝트
                </Button>
              )}
            </div>
            {projects.length === 0 ? (
              <p className="rounded-xl border p-5 text-sm text-muted-foreground">
                아직 프로젝트가 없습니다.
              </p>
            ) : (
              <ul className="divide-y rounded-xl border">
                {projects.map((project) => {
                  const isOpen = expanded.includes(project.id);
                  const projectPeople = listProjectPeople(project, people);
                  return (
                    <li key={project.id}>
                      <div className="flex items-center gap-2 p-2">
                        <button
                          type="button"
                          aria-expanded={isOpen}
                          aria-controls={`project-${project.id}`}
                          onClick={() => openProject(project)}
                          className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-2 text-left hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
                        >
                          <ChevronDown
                            className={`size-4 shrink-0 transition-transform ${isOpen ? "rotate-180" : ""}`}
                          />
                          <span className="truncate font-medium">{project.name}</span>
                          {project.archivedAt && (
                            <span className="shrink-0 text-xs text-muted-foreground">보관됨</span>
                          )}
                        </button>
                        {!isDemo && (
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            aria-label={`${project.name}에 참여자 추가`}
                            disabled={busy || Boolean(project.archivedAt)}
                            onClick={() => openAdd(project)}
                          >
                            <UserPlus className="size-4" />
                          </Button>
                        )}
                      </div>
                      {isOpen && (
                        <div
                          id={`project-${project.id}`}
                          className="space-y-3 border-t px-4 py-3 text-sm"
                        >
                          {project.goal && <p>{project.goal}</p>}
                          {project.description && (
                            <p className="text-muted-foreground">{project.description}</p>
                          )}
                          <p className="text-xs text-muted-foreground">
                            담당:{" "}
                            {people.find((item) => item.id === project.ownerPersonId)?.name ??
                              "없음"}{" "}
                            · 기간: {project.startsOn ?? "미정"} – {project.endsOn ?? "미정"}
                          </p>
                          <div>
                            <h3 className="mb-2 text-xs font-medium text-muted-foreground">
                              담당 및 참여자
                            </h3>
                            <div className="flex flex-wrap gap-2">
                              {projectPeople.length ? (
                                projectPeople.map(({ id, person: projectPerson, isOwner }) => {
                                  return projectPerson ? (
                                    <button
                                      key={id}
                                      type="button"
                                      onClick={() => openPerson(projectPerson)}
                                      className="rounded-md border px-2 py-1 hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
                                    >
                                      {projectPerson.name}
                                      {isOwner ? " · 담당" : ""}
                                      {projectPerson.archivedAt ? " · 보관됨" : ""}
                                    </button>
                                  ) : (
                                    <span
                                      key={id}
                                      className="rounded-md border px-2 py-1 text-muted-foreground"
                                    >
                                      목록에 없음
                                    </span>
                                  );
                                })
                              ) : (
                                <span className="text-muted-foreground">아직 없음</span>
                              )}
                            </div>
                          </div>
                          {!isDemo && (
                            <div className="flex gap-2">
                              <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                disabled={busy}
                                onClick={() => openProjectEditor(project)}
                              >
                                편집
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                variant="ghost"
                                disabled={busy}
                                onClick={() =>
                                  void act(() =>
                                    api
                                      .updateProject(workspaceId, project.id, {
                                        archived: !project.archivedAt,
                                      })
                                      .then(() => undefined),
                                  )
                                }
                              >
                                {project.archivedAt ? "복원" : "보관"}
                              </Button>
                            </div>
                          )}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
          <section aria-labelledby="unassigned-heading">
            <div className="rounded-xl border">
              <h2 id="unassigned-heading" className="font-medium">
                <button
                  type="button"
                  className="flex w-full items-center gap-2 p-4 text-left hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
                  aria-expanded={unassignedOpen}
                  aria-controls="unassigned-people"
                  onClick={() => setUnassignedOpen((value) => !value)}
                >
                  <ChevronDown
                    className={`size-4 transition-transform ${unassignedOpen ? "rotate-180" : ""}`}
                  />
                  <span>프로젝트에 속하지 않은 참여자</span>
                  <span className="ml-auto text-xs text-muted-foreground">
                    {unassigned.length}명
                  </span>
                </button>
              </h2>
              {unassignedOpen && (
                <div id="unassigned-people" className="flex flex-wrap gap-2 border-t p-4">
                  {unassigned.length ? (
                    unassigned.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        className="rounded-md border px-2 py-1 text-sm hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
                        onClick={() => openPerson(item)}
                      >
                        {item.name}
                        {item.archivedAt ? " · 보관됨" : ""}
                      </button>
                    ))
                  ) : (
                    <p className="text-sm text-muted-foreground">아직 없습니다.</p>
                  )}
                </div>
              )}
            </div>
          </section>
        </>
      )}

      <Dialog
        open={Boolean(projectDialog && loadedWorkspaceId === workspaceId)}
        onOpenChange={(open) => {
          if (!open && !busy) closeProjectEditor();
        }}
      >
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{projectDialog === "edit" ? "프로젝트 편집" : "새 프로젝트"}</DialogTitle>
            <DialogDescription>프로젝트 정보를 입력합니다.</DialogDescription>
          </DialogHeader>
          <form onSubmit={submitProject} className="grid gap-3 md:grid-cols-2">
            <Input
              aria-label="프로젝트 이름"
              placeholder="프로젝트 이름"
              value={projectForm.name}
              required
              maxLength={120}
              onChange={(event) =>
                setProjectForm((form) => ({ ...form, name: event.target.value }))
              }
            />
            <Input
              aria-label="프로젝트 목표"
              placeholder="목표"
              value={projectForm.goal}
              maxLength={4000}
              onChange={(event) =>
                setProjectForm((form) => ({ ...form, goal: event.target.value }))
              }
            />
            <Input
              aria-label="프로젝트 설명"
              placeholder="설명"
              value={projectForm.description}
              maxLength={4000}
              onChange={(event) =>
                setProjectForm((form) => ({ ...form, description: event.target.value }))
              }
            />
            <select
              aria-label="프로젝트 담당자"
              value={projectForm.ownerPersonId}
              onChange={(event) =>
                setProjectForm((form) => ({ ...form, ownerPersonId: event.target.value }))
              }
              className="min-h-9 rounded-md border bg-background px-3 text-sm"
            >
              <option value="">담당자 없음</option>
              {projectForm.ownerPersonId && !selectedOwner && (
                <option value={projectForm.ownerPersonId}>목록에 없음 · 변경 필요</option>
              )}
              {people
                .filter((item) => !item.archivedAt || item.id === projectForm.ownerPersonId)
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                    {item.archivedAt ? " (보관됨 · 변경 필요)" : ""}
                  </option>
                ))}
            </select>
            {projectDialog === "edit" && (
              <fieldset className="space-y-2 rounded-md border p-3 text-sm md:col-span-2">
                <legend className="px-1 font-medium">프로젝트 참여자</legend>
                <div className="flex flex-wrap gap-3">
                  {people
                    .filter(
                      (item) => !item.archivedAt || projectForm.participantIds.includes(item.id),
                    )
                    .map((item) => (
                      <label key={item.id} className="flex items-center gap-1">
                        <input
                          type="checkbox"
                          checked={projectForm.participantIds.includes(item.id)}
                          disabled={
                            Boolean(item.archivedAt) &&
                            !projectForm.participantIds.includes(item.id)
                          }
                          onChange={(event) =>
                            setProjectForm((form) => ({
                              ...form,
                              participantIds: event.target.checked
                                ? [...form.participantIds, item.id]
                                : form.participantIds.filter((id) => id !== item.id),
                            }))
                          }
                        />
                        {item.name}
                        {item.archivedAt ? " (보관됨)" : ""}
                      </label>
                    ))}
                </div>
              </fieldset>
            )}
            {invalidOwner && (
              <p role="alert" className="text-xs text-destructive md:col-span-2">
                활성 참여자를 담당자로 다시 선택해 주세요.
              </p>
            )}
            <label className="text-xs text-muted-foreground">
              시작일
              <Input
                type="date"
                value={projectForm.startsOn}
                onChange={(event) =>
                  setProjectForm((form) => ({ ...form, startsOn: event.target.value }))
                }
              />
            </label>
            <label className="text-xs text-muted-foreground">
              종료일
              <Input
                type="date"
                value={projectForm.endsOn}
                min={projectForm.startsOn}
                onChange={(event) =>
                  setProjectForm((form) => ({ ...form, endsOn: event.target.value }))
                }
              />
            </label>
            <div className="flex justify-end gap-2 md:col-span-2">
              <Button type="button" variant="outline" disabled={busy} onClick={closeProjectEditor}>
                취소
              </Button>
              <Button
                type="submit"
                disabled={
                  busy ||
                  invalidOwner ||
                  !projectForm.name.trim() ||
                  Boolean(
                    projectForm.startsOn &&
                    projectForm.endsOn &&
                    projectForm.endsOn < projectForm.startsOn,
                  )
                }
              >
                {busy ? "저장 중…" : "저장"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(addProject)}
        onOpenChange={(open) => {
          if (!open && !busy) closeAdd();
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{addProject?.name}에 참여자 추가</DialogTitle>
            <DialogDescription>기존 참여자를 선택하거나 새 참여자를 등록합니다.</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={submitAdd}>
            <div className="flex gap-2">
              <Button
                type="button"
                variant={addMode === "existing" ? "default" : "outline"}
                disabled={busy || Boolean(createdPersonId)}
                onClick={() => setAddMode("existing")}
              >
                기존 참여자
              </Button>
              <Button
                type="button"
                variant={addMode === "new" ? "default" : "outline"}
                disabled={busy}
                onClick={() => setAddMode("new")}
              >
                새 참여자
              </Button>
            </div>
            {addMode === "existing" ? (
              <select
                aria-label="기존 참여자"
                required
                value={selectedPersonId}
                onChange={(event) => setSelectedPersonId(event.target.value)}
                className="min-h-9 w-full rounded-md border bg-background px-3 text-sm"
              >
                <option value="">참여자 선택</option>
                {availablePeople.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                    {item.email ? ` · ${item.email}` : ""}
                  </option>
                ))}
              </select>
            ) : (
              <div className="space-y-2">
                <Input
                  aria-label="새 참여자 이름"
                  placeholder="이름"
                  value={newPerson.name}
                  required
                  maxLength={120}
                  disabled={Boolean(createdPersonId)}
                  onChange={(event) =>
                    setNewPerson((form) => ({ ...form, name: event.target.value }))
                  }
                />
                <Input
                  aria-label="새 참여자 이메일"
                  placeholder="이메일"
                  type="email"
                  value={newPerson.email}
                  required
                  maxLength={320}
                  disabled={Boolean(createdPersonId)}
                  onChange={(event) =>
                    setNewPerson((form) => ({ ...form, email: event.target.value }))
                  }
                />
                {createdPersonId && (
                  <p role="status" className="text-xs text-muted-foreground">
                    참여자가 등록되었습니다. 프로젝트 연결을 다시 시도할 수 있습니다.
                  </p>
                )}
              </div>
            )}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" disabled={busy} onClick={closeAdd}>
                취소
              </Button>
              <Button
                type="submit"
                disabled={
                  busy ||
                  (addMode === "existing"
                    ? !selectedPersonId
                    : !newPerson.name.trim() || !newPerson.email.trim())
                }
              >
                {busy ? "추가 중…" : "추가"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(person)}
        onOpenChange={(open) => {
          if (!open && !busy) closePerson();
        }}
      >
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{person?.name ?? "참여자"}</DialogTitle>
            <DialogDescription>
              기본 정보와 연결된 프로젝트, 업무, 결정, 이벤트를 살펴봅니다.
            </DialogDescription>
          </DialogHeader>
          {person && (
            <div className="space-y-5 text-sm">
              {personEditing && !isDemo ? (
                <form className="grid gap-2 md:grid-cols-2" onSubmit={submitPerson}>
                  <Input
                    aria-label="참여자 이름"
                    value={personForm.name}
                    required
                    maxLength={120}
                    onChange={(event) =>
                      setPersonForm((form) => ({ ...form, name: event.target.value }))
                    }
                  />
                  <Input
                    aria-label="참여자 이메일"
                    type="email"
                    value={personForm.email}
                    maxLength={320}
                    onChange={(event) =>
                      setPersonForm((form) => ({ ...form, email: event.target.value }))
                    }
                  />
                  <Input
                    aria-label="참여자 별칭"
                    placeholder="별칭 (쉼표 구분)"
                    value={personForm.aliases}
                    onChange={(event) =>
                      setPersonForm((form) => ({ ...form, aliases: event.target.value }))
                    }
                  />
                  <Input
                    aria-label="참여자 역할"
                    value={personForm.role}
                    maxLength={120}
                    onChange={(event) =>
                      setPersonForm((form) => ({ ...form, role: event.target.value }))
                    }
                  />
                  <div className="flex gap-2 md:col-span-2">
                    <Button type="submit" disabled={busy || !personForm.name.trim()}>
                      저장
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={busy}
                      onClick={() => setPersonEditing(false)}
                    >
                      취소
                    </Button>
                  </div>
                </form>
              ) : (
                <section className="space-y-1">
                  <h3 className="font-medium">기본 정보</h3>
                  <p>{person.email ?? "이메일 없음"}</p>
                  {person.role && <p>{person.role}</p>}
                  {person.aliases.length > 0 && (
                    <p className="text-muted-foreground">별칭: {person.aliases.join(", ")}</p>
                  )}
                  {person.archivedAt && <p className="text-muted-foreground">보관됨</p>}
                </section>
              )}
              <section className="space-y-2">
                <h3 className="font-medium">프로젝트</h3>
                {personContext?.projects.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className="block rounded-md border px-2 py-1 hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
                    onClick={() => {
                      closePerson();
                      setExpanded((current) =>
                        current.includes(item.id) ? current : [...current, item.id],
                      );
                      setLink("project", item.id);
                    }}
                  >
                    {item.name}
                  </button>
                ))}
                {!personContext?.projects.length && (
                  <p className="text-muted-foreground">연결된 프로젝트가 없습니다.</p>
                )}
              </section>
              {graphStatus === "loading" ? (
                <p role="status" className="text-muted-foreground">
                  업무와 결정, 이벤트를 불러오는 중입니다.
                </p>
              ) : graphStatus === "error" ? (
                <div role="alert" className="space-y-2">
                  <p className="text-destructive">연결 정보를 불러오지 못했습니다. {graphError}</p>
                  <Button type="button" variant="outline" size="sm" onClick={invalidateGraph}>
                    다시 시도
                  </Button>
                </div>
              ) : (
                <>
                  <section className="space-y-2">
                    <h3 className="font-medium">업무와 작업</h3>
                    <ActivityList
                      items={personContext?.tasks ?? []}
                      empty="연결된 업무가 없습니다."
                      workspaceId={workspaceId}
                    />
                  </section>
                  <section className="space-y-2">
                    <h3 className="font-medium">결정</h3>
                    <ActivityList
                      items={personContext?.decisions ?? []}
                      empty="연결된 결정이 없습니다."
                      workspaceId={workspaceId}
                    />
                  </section>
                  <section className="space-y-2">
                    <h3 className="font-medium">이벤트와 회의</h3>
                    <ActivityList
                      items={personContext?.events ?? []}
                      empty="참여가 확인된 이벤트가 없습니다."
                      workspaceId={workspaceId}
                    />
                  </section>
                </>
              )}
              {!isDemo && !personEditing && (
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    disabled={busy}
                    onClick={() => setPersonEditing(true)}
                  >
                    편집
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={busy}
                    onClick={() =>
                      void act(() =>
                        api
                          .updatePerson(workspaceId, person.id, { archived: !person.archivedAt })
                          .then(() => undefined),
                      )
                    }
                  >
                    {person.archivedAt ? "복원" : "보관"}
                  </Button>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
