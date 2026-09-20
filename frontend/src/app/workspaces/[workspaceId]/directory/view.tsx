"use client";

import { use, useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ChevronDown, UserPlus } from "lucide-react";
import { toast } from "sonner";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/common/state-views";
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
import { useApi, useDemoMode } from "@/lib/api/context";
import type { KnowledgeGraph, WorkspacePerson, WorkspaceProject } from "@/lib/api";
import { ActivityList } from "@/features/directory/components/activity-list";
import { buildPersonContext } from "@/features/directory/lib/person-context";
import { DiscardConfirmDialog } from "@/features/directory/components/discard-confirm-dialog";
import { FormField, NativeSelect, Textarea } from "@/features/directory/components/form-field";
import {
  emptyPerson,
  emptyProject,
  isFormDirty,
  parseAliases,
  personFormFrom,
  projectDateError,
  projectFormFrom,
  type PersonForm,
  type ProjectForm,
} from "@/features/directory/lib/directory-forms";
import { directoryToast, mutationErrorMessage } from "@/features/directory/lib/directory-messages";
import { listProjectPeople } from "@/features/directory/lib/project-people";
import { workspaceNavItems } from "@/lib/navigation";

// 화면 제목은 메뉴 이름과 같아야 합니다. 한쪽만 바뀌지 않도록 메뉴에서 읽어 옵니다.
const pageTitle =
  workspaceNavItems.find((item) => item.segment === "directory")?.label ?? "참여자·프로젝트";

function toError(cause: unknown): Error {
  return cause instanceof Error ? cause : new Error(String(cause));
}

/** 열어 둔 참여자·프로젝트를 주소에 남깁니다. 새로 고치거나 링크를 공유해도 같은 자리가 열립니다. */
function replaceDirectoryLink(kind?: "person" | "project", id?: string) {
  const url = new URL(window.location.href);
  url.searchParams.delete("person");
  url.searchParams.delete("project");
  if (kind && id) url.searchParams.set(kind, id);
  window.history.replaceState(null, "", url);
}

type ActOptions = {
  /** 무엇을 했는지 그대로 적은 완료 문구 */
  success: string;
  /** 있으면 완료 토스트에 "되돌리기"를 붙입니다. */
  undo?: () => void;
  onSuccess?: () => void;
};

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
  const [loadError, setLoadError] = useState<Error>();
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [expanded, setExpanded] = useState<string[]>([]);
  const [unassignedOpen, setUnassignedOpen] = useState(false);
  const [projectDialog, setProjectDialog] = useState<"create" | "edit" | null>(null);
  const createdProjectRef = useRef<string | undefined>(undefined);
  const [personId, setPersonId] = useState<string>();
  const [addProjectId, setAddProjectId] = useState<string>();
  // 프로젝트 없이 참여자만 등록하는 경우. 프로젝트가 하나도 없어도 참여자를 등록할 수 있어야 합니다.
  const [addStandalone, setAddStandalone] = useState(false);
  const [discard, setDiscard] = useState<{ run: () => void } | null>(null);
  const [personEditing, setPersonEditing] = useState(false);
  const [personForm, setPersonForm] = useState<PersonForm>(emptyPerson);
  const [projectForm, setProjectForm] = useState<ProjectForm>(emptyProject);
  // 닫을 때 입력이 바뀌었는지 비교할 기준입니다.
  const [projectInitial, setProjectInitial] = useState<ProjectForm>(emptyProject);
  const [editingProjectId, setEditingProjectId] = useState<string>();
  const [selectedPersonId, setSelectedPersonId] = useState("");
  const [newPerson, setNewPerson] = useState<PersonForm>(emptyPerson);
  const [addMode, setAddMode] = useState<"existing" | "new">("existing");
  const createdPersonRef = useRef<string | undefined>(undefined);
  const [createdPersonId, setCreatedPersonId] = useState<string>();
  const [graph, setGraph] = useState<KnowledgeGraph | null>(null);
  const [graphStatus, setGraphStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [graphError, setGraphError] = useState<Error>();
  const [graphRetry, setGraphRetry] = useState(0);
  const graphCacheRef = useRef<
    { api: typeof api; workspaceId: string; graph: KnowledgeGraph } | undefined
  >(undefined);
  const graphRequestRef = useRef<AbortController | null>(null);
  const graphRequestId = useRef(0);
  const initialLinkHandled = useRef(false);
  const workspaceIdRef = useRef(workspaceId);
  workspaceIdRef.current = workspaceId;

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
          setLoadError(toError(error));
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
    setAddStandalone(false);
    setDiscard(null);
  }, [workspaceId]);
  useEffect(() => {
    if (loading || loadError || loadedWorkspaceId !== workspaceId || initialLinkHandled.current)
      return;
    initialLinkHandled.current = true;
    const query = new URLSearchParams(window.location.search);
    const personParam = query.get("person");
    const projectParam = query.get("project");
    const linkedPerson = people.find((item) => item.id === personParam);
    const linkedProject = projects.find((item) => item.id === projectParam);
    if (linkedPerson) {
      setPersonId(linkedPerson.id);
      setPersonForm(personFormFrom(linkedPerson));
    } else if (linkedProject) {
      setExpanded((current) =>
        current.includes(linkedProject.id) ? current : [...current, linkedProject.id],
      );
    } else if (personParam || projectParam) {
      // 지워졌거나 다른 워크스페이스의 링크입니다. 아무 반응이 없으면 고장으로 보입니다.
      toast.error(personParam ? directoryToast.personMissing : directoryToast.projectMissing);
      replaceDirectoryLink();
    }
  }, [loading, loadError, loadedWorkspaceId, workspaceId, people, projects]);
  useEffect(() => {
    const onPopState = () => {
      const query = new URLSearchParams(window.location.search);
      const linkedPerson = people.find((item) => item.id === query.get("person"));
      setPersonId(linkedPerson?.id);
      setPersonEditing(false);
      if (linkedPerson) setPersonForm(personFormFrom(linkedPerson));
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
          setGraphError(toError(error));
          setGraphStatus("error");
        }
      })
      .finally(() => {
        if (graphRequestRef.current === controller) graphRequestRef.current = null;
      });
    return () => controller.abort();
  }, [api, workspaceId, loadedWorkspaceId, personId, graphRetry]);
  const setLink = replaceDirectoryLink;
  const act = async (action: () => Promise<void>, options: ActOptions) => {
    if (busyRef.current || isDemo) return;
    busyRef.current = true;
    setBusy(true);
    let failure: { error: unknown } | undefined;
    try {
      await action();
      await reload();
      options.onSuccess?.();
    } catch (error) {
      failure = { error };
      await reload().catch(() => undefined);
    } finally {
      invalidateGraph();
      busyRef.current = false;
      setBusy(false);
    }
    // 토스트는 잠금을 푼 뒤에 띄웁니다. "되돌리기"를 바로 눌러도 막히지 않습니다.
    if (failure) toast.error(mutationErrorMessage(failure.error));
    else
      toast.success(
        options.success,
        options.undo ? { action: { label: "되돌리기", onClick: options.undo } } : undefined,
      );
  };
  const actRef = useRef(act);
  actRef.current = act;

  /** 보관은 바로 실행하고, 실수였다면 토스트의 "되돌리기"로 복원합니다. */
  const setProjectArchived = (project: WorkspaceProject, archived: boolean) =>
    void actRef.current(
      () => api.updateProject(workspaceId, project.id, { archived }).then(() => undefined),
      {
        success: archived
          ? directoryToast.projectArchived(project.name)
          : directoryToast.projectRestored(project.name),
        undo: archived
          ? () => {
              if (workspaceIdRef.current === workspaceId) setProjectArchived(project, false);
            }
          : undefined,
      },
    );
  const setPersonArchived = (target: WorkspacePerson, archived: boolean) =>
    void actRef.current(
      () => api.updatePerson(workspaceId, target.id, { archived }).then(() => undefined),
      {
        success: archived
          ? directoryToast.personArchived(target.name)
          : directoryToast.personRestored(target.name),
        undo: archived
          ? () => {
              if (workspaceIdRef.current === workspaceId) setPersonArchived(target, false);
            }
          : undefined,
      },
    );

  /** 입력이 바뀌었으면 닫기 전에 확인합니다. 저장 중에는 닫지 않습니다. */
  const guardClose = (isDirty: boolean, close: () => void) => {
    if (busyRef.current) return;
    if (isDirty) setDiscard({ run: close });
    else close();
  };

  const openPerson = (person: WorkspacePerson) => {
    setPersonId(person.id);
    setPersonEditing(false);
    setPersonForm(personFormFrom(person));
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
    const form = project ? projectFormFrom(project) : emptyProject;
    setProjectForm(form);
    setProjectInitial(form);
    setProjectDialog(project ? "edit" : "create");
  };
  const closeProjectEditor = () => {
    createdProjectRef.current = undefined;
    setEditingProjectId(undefined);
    setProjectDialog(null);
  };
  /** 프로젝트를 넘기면 그 프로젝트에 연결하고, 비우면 참여자만 등록합니다. */
  const openAdd = (project?: WorkspaceProject) => {
    setAddProjectId(project?.id);
    setAddStandalone(!project);
    setSelectedPersonId("");
    setNewPerson(emptyPerson);
    setCreatedPersonId(undefined);
    createdPersonRef.current = undefined;
    setAddMode(project ? "existing" : "new");
  };
  const closeAdd = () => {
    setAddProjectId(undefined);
    setAddStandalone(false);
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
    const isCreate = !(editingProjectId ?? createdProjectRef.current);
    void act(
      async () => {
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
      },
      {
        success: isCreate
          ? directoryToast.projectCreated(input.name)
          : directoryToast.projectSaved(input.name),
        onSuccess: closeProjectEditor,
      },
    );
  };
  const submitPerson = (event: FormEvent) => {
    event.preventDefault();
    if (!personId) return;
    const input = {
      name: personForm.name.trim(),
      email: personForm.email.trim() || null,
      aliases: parseAliases(personForm.aliases),
      role: personForm.role.trim() || null,
    };
    void act(() => api.updatePerson(workspaceId, personId, input).then(() => undefined), {
      success: directoryToast.personSaved,
      onSuccess: () => setPersonEditing(false),
    });
  };
  const submitAdd = (event: FormEvent) => {
    event.preventDefault();
    const projectId = addProjectId;
    if (!projectId && !addStandalone) return;
    void act(
      async () => {
        let id = selectedPersonId;
        if (addMode === "new") {
          if (!createdPersonRef.current) {
            const person = await api.createPerson(workspaceId, {
              name: newPerson.name.trim(),
              // 이메일은 서버에서도 선택 항목입니다. 비우면 null로 보냅니다.
              email: newPerson.email.trim() || null,
              aliases: [],
              role: null,
            });
            createdPersonRef.current = person.id;
            setCreatedPersonId(person.id);
          }
          id = createdPersonRef.current;
        }
        if (!projectId) {
          // 새로 등록한 참여자는 아직 어느 프로젝트에도 없으므로 그 목록을 펼쳐 결과를 보여줍니다.
          setUnassignedOpen(true);
          return;
        }
        // Fetch current revision immediately before changing the participant set.
        const current = (await api.listProjects(workspaceId)).find((item) => item.id === projectId);
        if (!current) throw new Error("프로젝트를 찾을 수 없습니다.");
        if (current.participantIds?.includes(id)) return;
        await api.setProjectParticipants(workspaceId, projectId, {
          revision: current.revision ?? 0,
          personIds: [...(current.participantIds ?? []), id],
        });
      },
      { success: directoryToast.personAdded, onSuccess: closeAdd },
    );
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
  const dateError = projectDateError(projectForm);
  const isProjectDirty = isFormDirty(projectForm, projectInitial);
  const isPersonDirty = Boolean(
    person && personEditing && isFormDirty(personForm, personFormFrom(person)),
  );
  // 참여자를 이미 등록했다면(프로젝트 연결만 실패) 닫아도 잃는 입력이 없습니다.
  const isAddDirty =
    !createdPersonId &&
    Boolean(selectedPersonId || newPerson.name.trim() || newPerson.email.trim());
  const availablePeople = people.filter(
    (item) => !item.archivedAt && !(addProject?.participantIds ?? []).includes(item.id),
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title={pageTitle}
        description={
          isDemo
            ? "공개 데모의 실제 워크스페이스 데이터를 읽기 전용으로 살펴봅니다."
            : "프로젝트를 열어 참여자와 업무 맥락을 살펴봅니다."
        }
      />
      {isDemo && <DemoAuthGuidance />}
      {loading || (loadedWorkspaceId !== workspaceId && !loadError) ? (
        <ListSkeleton count={3} className="h-14" label="참여자와 프로젝트를 불러오는 중" />
      ) : loadError ? (
        <ErrorState
          error={loadError}
          onRetry={() => {
            setLoading(true);
            void reload()
              .catch((error) => setLoadError(toError(error)))
              .finally(() => setLoading(false));
          }}
        />
      ) : (
        <>
          <section aria-labelledby="projects-heading" className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h2 id="projects-heading" className="text-lg font-semibold">
                프로젝트
              </h2>
              {!isDemo && projects.length > 0 && (
                <Button type="button" disabled={busy} onClick={() => openProjectEditor()}>
                  새 프로젝트
                </Button>
              )}
            </div>
            {projects.length === 0 ? (
              <EmptyState
                title="아직 프로젝트가 없습니다"
                description="프로젝트를 만들면 회의와 문서를 프로젝트별로 묶어 볼 수 있어요."
                action={
                  isDemo ? null : (
                    <Button type="button" size="sm" onClick={() => openProjectEditor()}>
                      새 프로젝트
                    </Button>
                  )
                }
              />
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
                            aria-hidden
                            className={`size-4 shrink-0 transition-transform motion-reduce:transition-none ${isOpen ? "rotate-180" : ""}`}
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
                            title="참여자 추가"
                            disabled={busy || Boolean(project.archivedAt)}
                            onClick={() => openAdd(project)}
                          >
                            <UserPlus className="size-4" aria-hidden />
                          </Button>
                        )}
                      </div>
                      {isOpen && (
                        <div
                          id={`project-${project.id}`}
                          className="space-y-3 border-t px-4 py-3 text-sm"
                        >
                          {project.goal && <p className="whitespace-pre-line">{project.goal}</p>}
                          {project.description && (
                            <p className="whitespace-pre-line text-muted-foreground">
                              {project.description}
                            </p>
                          )}
                          <p className="text-xs text-muted-foreground">
                            담당자:{" "}
                            {people.find((item) => item.id === project.ownerPersonId)?.name ??
                              "없음"}{" "}
                            · 기간: {project.startsOn ?? "미정"} – {project.endsOn ?? "미정"}
                          </p>
                          <div>
                            <h3 className="mb-2 text-xs font-medium text-muted-foreground">
                              담당자와 참여자
                            </h3>
                            <div className="flex flex-wrap items-center gap-2">
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
                                      {isOwner ? " · 담당자" : ""}
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
                                <>
                                  <span className="text-muted-foreground">
                                    아직 참여자가 없습니다.
                                  </span>
                                  {!isDemo && !project.archivedAt && (
                                    <Button
                                      type="button"
                                      size="xs"
                                      variant="outline"
                                      disabled={busy}
                                      onClick={() => openAdd(project)}
                                    >
                                      참여자 추가
                                    </Button>
                                  )}
                                </>
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
                                onClick={() => setProjectArchived(project, !project.archivedAt)}
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
          <section aria-labelledby="people-heading" className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h2 id="people-heading" className="text-lg font-semibold">
                참여자
              </h2>
              {/* 프로젝트가 하나도 없어도 참여자를 등록할 수 있어야 합니다. */}
              {!isDemo && people.length > 0 && (
                <Button type="button" variant="outline" disabled={busy} onClick={() => openAdd()}>
                  <UserPlus aria-hidden />
                  참여자 추가
                </Button>
              )}
            </div>
            {people.length === 0 ? (
              <EmptyState
                className="p-6"
                icon={<UserPlus className="size-5" />}
                title="아직 등록한 참여자가 없습니다"
                description={
                  isDemo
                    ? undefined
                    : "참여자를 등록해 두면 프로젝트 담당자와 회의 참석자로 연결할 수 있어요."
                }
                action={
                  isDemo ? null : (
                    <Button type="button" size="sm" variant="outline" onClick={() => openAdd()}>
                      참여자 추가
                    </Button>
                  )
                }
              />
            ) : (
              <div className="rounded-xl border">
                <h3 id="unassigned-heading" className="font-medium">
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 rounded-xl p-4 text-left hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
                    aria-expanded={unassignedOpen}
                    aria-controls="unassigned-people"
                    onClick={() => setUnassignedOpen((value) => !value)}
                  >
                    <ChevronDown
                      aria-hidden
                      className={`size-4 transition-transform motion-reduce:transition-none ${unassignedOpen ? "rotate-180" : ""}`}
                    />
                    <span>프로젝트에 속하지 않은 참여자</span>
                    <span className="ml-auto text-xs text-muted-foreground">
                      {unassigned.length}명
                    </span>
                  </button>
                </h3>
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
                      <p className="text-sm text-muted-foreground">
                        모든 참여자가 프로젝트에 속해 있습니다.
                      </p>
                    )}
                  </div>
                )}
              </div>
            )}
          </section>
        </>
      )}

      <Dialog
        open={Boolean(projectDialog && loadedWorkspaceId === workspaceId)}
        onOpenChange={(open) => {
          if (!open) guardClose(isProjectDirty, closeProjectEditor);
        }}
      >
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{projectDialog === "edit" ? "프로젝트 편집" : "새 프로젝트"}</DialogTitle>
            <DialogDescription>프로젝트 정보를 입력합니다.</DialogDescription>
          </DialogHeader>
          <form onSubmit={submitProject} className="grid gap-4 md:grid-cols-2">
            <FormField
              htmlFor="project-name"
              label="프로젝트 이름"
              required
              className="md:col-span-2"
            >
              <Input
                id="project-name"
                placeholder="예: 맥락이 출시 준비"
                value={projectForm.name}
                required
                maxLength={120}
                onChange={(event) =>
                  setProjectForm((form) => ({ ...form, name: event.target.value }))
                }
              />
            </FormField>
            <FormField htmlFor="project-goal" label="목표" className="md:col-span-2">
              <Textarea
                id="project-goal"
                placeholder="예: 10월 말까지 공개 베타를 연다"
                value={projectForm.goal}
                maxLength={4000}
                rows={3}
                onChange={(event) =>
                  setProjectForm((form) => ({ ...form, goal: event.target.value }))
                }
              />
            </FormField>
            <FormField htmlFor="project-description" label="설명" className="md:col-span-2">
              <Textarea
                id="project-description"
                placeholder="배경, 범위, 참고할 내용을 적습니다"
                value={projectForm.description}
                maxLength={4000}
                rows={4}
                onChange={(event) =>
                  setProjectForm((form) => ({ ...form, description: event.target.value }))
                }
              />
            </FormField>
            <FormField
              htmlFor="project-owner"
              label="담당자"
              className="md:col-span-2"
              error={
                invalidOwner ? "보관되지 않은 참여자를 담당자로 다시 선택해 주세요." : undefined
              }
              errorId="project-owner-error"
            >
              <NativeSelect
                id="project-owner"
                value={projectForm.ownerPersonId}
                aria-invalid={invalidOwner || undefined}
                aria-describedby={invalidOwner ? "project-owner-error" : undefined}
                onChange={(event) =>
                  setProjectForm((form) => ({ ...form, ownerPersonId: event.target.value }))
                }
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
              </NativeSelect>
            </FormField>
            {projectDialog === "edit" && (
              <fieldset className="space-y-2 rounded-md border p-3 text-sm md:col-span-2">
                <legend className="px-1 font-medium">
                  참여자 <span className="font-normal text-muted-foreground">(선택)</span>
                </legend>
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
                  {people.length === 0 && (
                    <p className="text-muted-foreground">아직 등록한 참여자가 없습니다.</p>
                  )}
                </div>
              </fieldset>
            )}
            <FormField htmlFor="project-starts-on" label="시작일">
              <Input
                id="project-starts-on"
                type="date"
                value={projectForm.startsOn}
                onChange={(event) =>
                  setProjectForm((form) => ({ ...form, startsOn: event.target.value }))
                }
              />
            </FormField>
            <FormField
              htmlFor="project-ends-on"
              label="종료일"
              error={dateError}
              errorId="project-ends-on-error"
            >
              <Input
                id="project-ends-on"
                type="date"
                value={projectForm.endsOn}
                min={projectForm.startsOn || undefined}
                aria-invalid={dateError ? true : undefined}
                aria-describedby={dateError ? "project-ends-on-error" : undefined}
                onChange={(event) =>
                  setProjectForm((form) => ({ ...form, endsOn: event.target.value }))
                }
              />
            </FormField>
            <div className="flex justify-end gap-2 md:col-span-2">
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => guardClose(isProjectDirty, closeProjectEditor)}
              >
                취소
              </Button>
              <Button
                type="submit"
                pending={busy}
                pendingLabel="저장하는 중…"
                disabled={invalidOwner || !projectForm.name.trim() || Boolean(dateError)}
              >
                저장
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(addProject) || (addStandalone && loadedWorkspaceId === workspaceId)}
        onOpenChange={(open) => {
          if (!open) guardClose(isAddDirty, closeAdd);
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {addProject ? `${addProject.name}에 참여자 추가` : "참여자 추가"}
            </DialogTitle>
            <DialogDescription>
              {addProject
                ? "기존 참여자를 선택하거나 새 참여자를 등록합니다."
                : "새 참여자를 등록합니다. 프로젝트에는 나중에 연결할 수 있어요."}
            </DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={submitAdd}>
            {addProject && (
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant={addMode === "existing" ? "default" : "outline"}
                  aria-pressed={addMode === "existing"}
                  disabled={busy || Boolean(createdPersonId)}
                  onClick={() => setAddMode("existing")}
                >
                  기존 참여자
                </Button>
                <Button
                  type="button"
                  variant={addMode === "new" ? "default" : "outline"}
                  aria-pressed={addMode === "new"}
                  disabled={busy}
                  onClick={() => setAddMode("new")}
                >
                  새 참여자
                </Button>
              </div>
            )}
            {addMode === "existing" ? (
              <FormField htmlFor="add-existing-person" label="기존 참여자" required>
                <NativeSelect
                  id="add-existing-person"
                  required
                  value={selectedPersonId}
                  onChange={(event) => setSelectedPersonId(event.target.value)}
                >
                  <option value="">참여자 선택</option>
                  {availablePeople.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                      {item.email ? ` · ${item.email}` : ""}
                    </option>
                  ))}
                </NativeSelect>
                {availablePeople.length === 0 && (
                  <p className="text-xs text-muted-foreground">
                    추가할 수 있는 참여자가 없습니다. 새 참여자로 등록할 수 있어요.
                  </p>
                )}
              </FormField>
            ) : (
              <div className="space-y-3">
                <FormField htmlFor="add-person-name" label="이름" required>
                  <Input
                    id="add-person-name"
                    placeholder="예: 김민지"
                    value={newPerson.name}
                    required
                    maxLength={120}
                    disabled={Boolean(createdPersonId)}
                    onChange={(event) =>
                      setNewPerson((form) => ({ ...form, name: event.target.value }))
                    }
                  />
                </FormField>
                {/* 이메일은 서버에서 선택 항목입니다. 추가와 편집 모두 같은 규칙을 씁니다. */}
                <FormField htmlFor="add-person-email" label="이메일">
                  <Input
                    id="add-person-email"
                    placeholder="예: minji@example.com"
                    type="email"
                    value={newPerson.email}
                    maxLength={320}
                    disabled={Boolean(createdPersonId)}
                    onChange={(event) =>
                      setNewPerson((form) => ({ ...form, email: event.target.value }))
                    }
                  />
                </FormField>
                {createdPersonId && (
                  <p role="status" className="text-xs text-muted-foreground">
                    참여자를 등록했습니다. 추가를 누르면 프로젝트 연결을 다시 시도합니다.
                  </p>
                )}
              </div>
            )}
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => guardClose(isAddDirty, closeAdd)}
              >
                취소
              </Button>
              <Button
                type="submit"
                pending={busy}
                pendingLabel="추가하는 중…"
                disabled={addMode === "existing" ? !selectedPersonId : !newPerson.name.trim()}
              >
                추가
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(person)}
        onOpenChange={(open) => {
          if (!open) guardClose(isPersonDirty, closePerson);
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
                <form className="grid gap-3 md:grid-cols-2" onSubmit={submitPerson}>
                  <FormField htmlFor="edit-person-name" label="이름" required>
                    <Input
                      id="edit-person-name"
                      placeholder="예: 김민지"
                      value={personForm.name}
                      required
                      maxLength={120}
                      onChange={(event) =>
                        setPersonForm((form) => ({ ...form, name: event.target.value }))
                      }
                    />
                  </FormField>
                  <FormField htmlFor="edit-person-email" label="이메일">
                    <Input
                      id="edit-person-email"
                      placeholder="예: minji@example.com"
                      type="email"
                      value={personForm.email}
                      maxLength={320}
                      onChange={(event) =>
                        setPersonForm((form) => ({ ...form, email: event.target.value }))
                      }
                    />
                  </FormField>
                  <FormField htmlFor="edit-person-aliases" label="별칭">
                    <Input
                      id="edit-person-aliases"
                      placeholder="예: 민지, MJ (쉼표로 구분)"
                      value={personForm.aliases}
                      onChange={(event) =>
                        setPersonForm((form) => ({ ...form, aliases: event.target.value }))
                      }
                    />
                  </FormField>
                  <FormField htmlFor="edit-person-role" label="역할">
                    <Input
                      id="edit-person-role"
                      placeholder="예: 프로덕트 매니저"
                      value={personForm.role}
                      maxLength={120}
                      onChange={(event) =>
                        setPersonForm((form) => ({ ...form, role: event.target.value }))
                      }
                    />
                  </FormField>
                  <div className="flex gap-2 md:col-span-2">
                    <Button
                      type="submit"
                      pending={busy}
                      pendingLabel="저장하는 중…"
                      disabled={!personForm.name.trim()}
                    >
                      저장
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={busy}
                      onClick={() =>
                        guardClose(isPersonDirty, () => {
                          // 버린 입력이 다음 편집에 남지 않도록 원본으로 되돌립니다.
                          setPersonEditing(false);
                          setPersonForm(personFormFrom(person));
                        })
                      }
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
                    onClick={() =>
                      guardClose(isPersonDirty, () => {
                        closePerson();
                        setExpanded((current) =>
                          current.includes(item.id) ? current : [...current, item.id],
                        );
                        setLink("project", item.id);
                      })
                    }
                  >
                    {item.name}
                  </button>
                ))}
                {!personContext?.projects.length && (
                  <p className="text-muted-foreground">연결된 프로젝트가 없습니다.</p>
                )}
              </section>
              {graphStatus === "loading" ? (
                <ListSkeleton
                  count={2}
                  className="h-12"
                  label="업무와 결정, 이벤트를 불러오는 중"
                />
              ) : graphStatus === "error" && graphError ? (
                <ErrorState
                  compact
                  error={graphError}
                  title="연결 정보를 불러오지 못했습니다"
                  onRetry={invalidateGraph}
                />
              ) : (
                <>
                  <section className="space-y-2">
                    <h3 className="font-medium">업무</h3>
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
                    onClick={() => {
                      // 편집은 항상 저장된 값에서 시작합니다.
                      setPersonForm(personFormFrom(person));
                      setPersonEditing(true);
                    }}
                  >
                    편집
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={busy}
                    onClick={() => setPersonArchived(person, !person.archivedAt)}
                  >
                    {person.archivedAt ? "복원" : "보관"}
                  </Button>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <DiscardConfirmDialog
        open={Boolean(discard)}
        onKeepEditing={() => setDiscard(null)}
        onDiscard={() => {
          discard?.run();
          setDiscard(null);
        }}
      />
    </div>
  );
}
