"use client";

import { use, useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { toast } from "sonner";
import Link from "next/link";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useApi, useDemoMode } from "@/lib/api/context";
import type { WorkspacePerson, WorkspaceProject } from "@/lib/api";

type PersonForm = { name: string; email: string; aliases: string; role: string };
type ProjectForm = { name: string; goal: string; description: string; ownerPersonId: string; participantIds: string[]; startsOn: string; endsOn: string };
const emptyPerson: PersonForm = { name: "", email: "", aliases: "", role: "" };
const emptyProject: ProjectForm = { name: "", goal: "", description: "", ownerPersonId: "", participantIds: [], startsOn: "", endsOn: "" };

export default function DirectoryPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  return <DirectoryView workspaceId={workspaceId} />;
}

export function DirectoryView({ workspaceId }: { workspaceId: string }) {
  const api = useApi();
  const isDemo = useDemoMode();
  const [people, setPeople] = useState<WorkspacePerson[]>([]);
  const [projects, setProjects] = useState<WorkspaceProject[]>([]);
  const [personForm, setPersonForm] = useState<PersonForm>(emptyPerson);
  const [projectForm, setProjectForm] = useState<ProjectForm>(emptyProject);
  const [editingPersonId, setEditingPersonId] = useState<string>();
  const [editingProjectId, setEditingProjectId] = useState<string>();
  const [busy, setBusy] = useState(false);
  const handledDeepLink = useRef(false);
  const reload = useCallback(async () => {
    const [newPeople, newProjects] = await Promise.all([api.listPeople(workspaceId), api.listProjects(workspaceId)]);
    setPeople(newPeople);
    setProjects(newProjects);
  }, [api, workspaceId]);
  useEffect(() => { void reload().catch((error) => toast.error(error instanceof Error ? error.message : "목록을 불러오지 못했습니다.")); }, [reload]);
  const act = async (action: () => Promise<unknown>) => {
    setBusy(true);
    try { await action(); await reload(); toast.success("저장했습니다."); }
    catch (error) { await reload().catch(() => undefined); toast.error(error instanceof Error ? error.message : "저장하지 못했습니다."); }
    finally { setBusy(false); }
  };
  const resetPerson = () => { setPersonForm(emptyPerson); setEditingPersonId(undefined); };
  const resetProject = () => { setProjectForm(emptyProject); setEditingProjectId(undefined); };
  const submitPerson = (event: FormEvent) => {
    event.preventDefault();
    const input = { name: personForm.name.trim(), email: personForm.email.trim() || null, aliases: personForm.aliases.split(",").map((item) => item.trim()).filter(Boolean), role: personForm.role.trim() || null };
    void act(async () => {
      if (editingPersonId) await api.updatePerson(workspaceId, editingPersonId, input);
      else await api.createPerson(workspaceId, input);
      resetPerson();
    });
  };
  const submitProject = (event: FormEvent) => {
    event.preventDefault();
    const input = { name: projectForm.name.trim(), goal: projectForm.goal.trim() || null, description: projectForm.description.trim() || null, ownerPersonId: projectForm.ownerPersonId || null, startsOn: projectForm.startsOn || null, endsOn: projectForm.endsOn || null };
    void act(async () => {
      const project = editingProjectId
        ? await api.updateProject(workspaceId, editingProjectId, input)
        : await api.createProject(workspaceId, input);
      const previous = new Set(project.participantIds ?? []);
      const next = new Set(projectForm.participantIds);
      if (previous.size !== next.size || [...next].some((id) => !previous.has(id))) {
        await api.setProjectParticipants(workspaceId, project.id, { revision: project.revision ?? 0, personIds: [...next] });
      }
      resetProject();
    });
  };
  const editPerson = (person: WorkspacePerson) => {
    setEditingPersonId(person.id);
    window.requestAnimationFrame(() => document.getElementById("person-editor")?.scrollIntoView({ behavior: "smooth", block: "start" }));
    setPersonForm({ name: person.name, email: person.email ?? "", aliases: person.aliases.join(", "), role: person.role ?? "" });
  };
  const editProject = (project: WorkspaceProject) => {
    setEditingProjectId(project.id);
    window.requestAnimationFrame(() => document.getElementById("project-editor")?.scrollIntoView({ behavior: "smooth", block: "start" }));
    setProjectForm({ name: project.name, goal: project.goal ?? "", description: project.description ?? "", ownerPersonId: project.ownerPersonId ?? "", participantIds: project.participantIds ?? [], startsOn: project.startsOn ?? "", endsOn: project.endsOn ?? "" });
  };
  useEffect(() => {
    if (isDemo || handledDeepLink.current || (!people.length && !projects.length)) return;
    const params = new URLSearchParams(window.location.search);
    const person = people.find((item) => item.id === params.get("person"));
    const project = projects.find((item) => item.id === params.get("project"));
    if (person) { handledDeepLink.current = true; editPerson(person); }
    else if (project) { handledDeepLink.current = true; editProject(project); }
    // This is only an initial deep link; editing must not reset on every list reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDemo, people.length, projects.length]);
  const selectedOwner = people.find((person) => person.id === projectForm.ownerPersonId);
  const invalidOwner = Boolean(projectForm.ownerPersonId && (!selectedOwner || selectedOwner.archivedAt));
  if (isDemo) return <div className="space-y-6"><PageHeader title="프로젝트와 참여자" description="공개 데모의 실제 워크스페이스 데이터를 읽기 전용으로 보여줍니다." /><p className="text-sm text-muted-foreground">변경하려면 <Link href="/login" className="underline">로그인</Link>해 내 워크스페이스를 사용하세요.</p><section className="space-y-2"><h2 className="text-lg font-semibold">프로젝트</h2>{projects.map((project) => <div key={project.id} className="space-y-1 rounded-lg border p-3 text-sm"><p className="font-medium">{project.name}{project.archivedAt ? " · 보관됨" : ""}</p>{project.goal && <p>{project.goal}</p>}<p className="text-muted-foreground">참여자: {(project.participantIds ?? []).map((id) => people.find((person) => person.id === id)?.name ?? "목록에 없음").join(", ") || "아직 없음"}</p></div>)}</section><section className="space-y-2"><h2 className="text-lg font-semibold">참여자</h2>{people.map((person) => <div key={person.id} className="rounded-lg border p-3 text-sm"><span className="font-medium">{person.name}</span>{person.email && <span className="ml-2 text-muted-foreground">{person.email}</span>}{person.role && <span className="ml-2 text-muted-foreground">{person.role}</span>}</div>)}</section></div>;
  return <div className="flex flex-col gap-8">
    <PageHeader title="참여자와 프로젝트" description="워크스페이스에서 여러 프로젝트와 회의 참여자를 관리합니다." />
    <section className="space-y-4" aria-labelledby="projects-heading">
      <h2 id="projects-heading" className="text-lg font-semibold">프로젝트</h2>
      <form id="project-editor" className="grid gap-2 rounded-xl border p-4 md:grid-cols-2" onSubmit={submitProject}>
        <Input aria-label="프로젝트 이름" placeholder="프로젝트 이름" value={projectForm.name} required maxLength={120} onChange={(event) => setProjectForm((form) => ({ ...form, name: event.target.value }))} />
        <Input aria-label="프로젝트 목표" placeholder="목표" value={projectForm.goal} maxLength={4000} onChange={(event) => setProjectForm((form) => ({ ...form, goal: event.target.value }))} />
        <Input aria-label="프로젝트 설명" placeholder="설명" value={projectForm.description} maxLength={4000} onChange={(event) => setProjectForm((form) => ({ ...form, description: event.target.value }))} />
        <select aria-label="프로젝트 담당자" value={projectForm.ownerPersonId} onChange={(event) => setProjectForm((form) => ({ ...form, ownerPersonId: event.target.value }))} className="rounded-md border bg-background px-3 text-sm"><option value="">담당자 없음</option>{projectForm.ownerPersonId && !selectedOwner && <option value={projectForm.ownerPersonId}>목록에 없음 · 변경 필요</option>}{people.filter((item) => !item.archivedAt || item.id === projectForm.ownerPersonId).map((item) => <option key={item.id} value={item.id}>{item.name}{item.archivedAt ? " (보관됨 · 변경 필요)" : ""}</option>)}</select>
        <fieldset className="space-y-1 rounded-md border p-2 text-sm md:col-span-2"><legend className="px-1 font-medium">프로젝트 참여자</legend><div className="flex flex-wrap gap-3">{people.filter((item) => !item.archivedAt || projectForm.participantIds.includes(item.id)).map((person) => <label key={person.id} className="flex items-center gap-1"><input type="checkbox" checked={projectForm.participantIds.includes(person.id)} disabled={Boolean(person.archivedAt) && !projectForm.participantIds.includes(person.id)} onChange={(event) => setProjectForm((form) => ({ ...form, participantIds: event.target.checked ? [...form.participantIds, person.id] : form.participantIds.filter((id) => id !== person.id) }))} />{person.name}{person.email ? ` · ${person.email}` : ""}{person.archivedAt ? " (보관됨)" : ""}</label>)}</div></fieldset>
        {invalidOwner && <p role="alert" className="text-xs text-destructive">활성 참여자를 담당자로 다시 선택해 주세요.</p>}
        <label className="text-xs text-muted-foreground">시작일<Input type="date" value={projectForm.startsOn} onChange={(event) => setProjectForm((form) => ({ ...form, startsOn: event.target.value }))} /></label>
        <label className="text-xs text-muted-foreground">종료일<Input type="date" value={projectForm.endsOn} min={projectForm.startsOn} onChange={(event) => setProjectForm((form) => ({ ...form, endsOn: event.target.value }))} /></label>
        <div className="flex gap-2"><Button disabled={busy || invalidOwner || !projectForm.name.trim() || Boolean(projectForm.startsOn && projectForm.endsOn && projectForm.endsOn < projectForm.startsOn)} type="submit">{editingProjectId ? "프로젝트 변경 저장" : "프로젝트 저장"}</Button>{editingProjectId && <Button type="button" variant="outline" disabled={busy} onClick={resetProject}>취소</Button>}</div>
      </form>
      <ul className="divide-y rounded-xl border">{projects.map((project) => <li key={project.id} className="space-y-2 p-3 text-sm"><div className="flex flex-wrap items-center gap-2"><span className="font-medium">{project.name}</span>{project.goal && <span className="text-muted-foreground">{project.goal}</span>}{project.description && <span className="text-muted-foreground">{project.description}</span>}{project.ownerPersonId && <span className="text-muted-foreground">담당: {people.find((person) => person.id === project.ownerPersonId)?.name ?? "목록에 없음"}</span>}{(project.startsOn || project.endsOn) && <span className="text-muted-foreground">{project.startsOn ?? "시작일 미정"} – {project.endsOn ?? "종료일 미정"}</span>}{project.archivedAt && <span className="text-muted-foreground">보관됨</span>}<div className="ml-auto flex gap-2"><Button variant="ghost" size="sm" disabled={busy} onClick={() => editProject(project)}>편집</Button><Button variant="outline" size="sm" disabled={busy} onClick={() => void act(() => api.updateProject(workspaceId, project.id, { archived: !project.archivedAt }))}>{project.archivedAt ? "복원" : "보관"}</Button></div></div><div className="space-y-1 border-l-2 pl-3"><p className="text-xs font-medium text-muted-foreground">프로젝트 참여자</p>{(project.participantIds ?? []).length ? (project.participantIds ?? []).map((id) => { const person = people.find((item) => item.id === id); return <div key={id} className="flex items-center gap-2"><span>{person?.name ?? "목록에 없음"}</span>{person?.email && <span className="text-xs text-muted-foreground">{person.email}</span>}{person && <Button variant="ghost" size="sm" onClick={() => editPerson(person)}>참여자 편집</Button>}</div>; }) : <p className="text-xs text-muted-foreground">아직 없음</p>}</div></li>)}</ul>
    </section>    <section className="space-y-4" aria-labelledby="people-heading">
      <h2 id="people-heading" className="text-lg font-semibold">참여자</h2>
      <form id="person-editor" className="grid gap-2 rounded-xl border p-4 md:grid-cols-3" onSubmit={submitPerson}>
        <Input aria-label="참여자 이름" placeholder="이름" value={personForm.name} required maxLength={120} onChange={(event) => setPersonForm((form) => ({ ...form, name: event.target.value }))} />
        <Input aria-label="참여자 이메일" placeholder="이메일" type="email" value={personForm.email} maxLength={320} onChange={(event) => setPersonForm((form) => ({ ...form, email: event.target.value }))} />
        <Input aria-label="참여자 별칭" placeholder="별칭 (쉼표 구분)" value={personForm.aliases} onChange={(event) => setPersonForm((form) => ({ ...form, aliases: event.target.value }))} />
        <Input aria-label="참여자 역할" placeholder="역할" value={personForm.role} maxLength={120} onChange={(event) => setPersonForm((form) => ({ ...form, role: event.target.value }))} />
        <div className="flex gap-2"><Button disabled={busy || !personForm.name.trim()} type="submit">{editingPersonId ? "참여자 변경 저장" : "참여자 저장"}</Button>{editingPersonId && <Button type="button" variant="outline" disabled={busy} onClick={resetPerson}>취소</Button>}</div>
      </form>
      <ul className="divide-y rounded-xl border">{people.map((person) => <li key={person.id} className="flex flex-wrap items-center gap-2 p-3 text-sm"><span className="font-medium">{person.name}</span>{person.email && <span className="text-muted-foreground">{person.email}</span>}{person.role && <span className="text-muted-foreground">{person.role}</span>}{person.aliases.length > 0 && <span className="text-muted-foreground">별칭: {person.aliases.join(", ")}</span>}{person.archivedAt && <span className="text-muted-foreground">보관됨</span>}<div className="ml-auto flex gap-2"><Button variant="ghost" size="sm" disabled={busy} onClick={() => editPerson(person)}>편집</Button><Button variant="outline" size="sm" disabled={busy} onClick={() => void act(() => api.updatePerson(workspaceId, person.id, { archived: !person.archivedAt }))}>{person.archivedAt ? "복원" : "보관"}</Button></div></li>)}</ul>
    </section>

  </div>;
}
