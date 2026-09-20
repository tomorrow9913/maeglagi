"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FormField } from "@/features/directory/components/form-field";
import { parseAliases, personFormFrom } from "@/features/directory/lib/directory-forms";
import { mutationErrorMessage } from "@/features/directory/lib/directory-messages";
import { useApi } from "@/lib/api/context";
import type { WorkspacePerson, WorkspaceProject } from "@/lib/api";

export function PersonDirectoryDetails({
  workspaceId,
  person,
  projects,
  readOnly,
  onSaved,
}: {
  workspaceId: string;
  person: WorkspacePerson;
  projects: WorkspaceProject[];
  readOnly: boolean;
  onSaved: () => void;
}) {
  const api = useApi();
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(() => personFormFrom(person));
  const [membership, setMembership] = useState(() =>
    projects
      .filter((project) => project.participantIds?.includes(person.id))
      .map((project) => project.id),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const related = projects.filter(
    (project) => project.ownerPersonId === person.id || project.participantIds?.includes(person.id),
  );

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || !form.name.trim()) return;
    setBusy(true);
    setError(undefined);
    try {
      await api.updatePerson(workspaceId, person.id, {
        name: form.name.trim(),
        email: form.email.trim() || null,
        aliases: parseAliases(form.aliases),
        role: form.role.trim() || null,
      });
      for (const project of projects) {
        const wasMember = project.participantIds?.includes(person.id) ?? false;
        const shouldBeMember = membership.includes(project.id);
        if (wasMember === shouldBeMember) continue;
        await api.setProjectParticipants(workspaceId, project.id, {
          revision: project.revision ?? 0,
          personIds: shouldBeMember
            ? [...new Set([...(project.participantIds ?? []), person.id])]
            : (project.participantIds ?? []).filter((id) => id !== person.id),
        });
      }
      setEditing(false);
      onSaved();
    } catch (cause) {
      setError(mutationErrorMessage(cause));
      // A preceding request may already have succeeded; refresh revisions before another save.
      onSaved();
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="space-y-3 text-sm" aria-label="참여자 정보">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium text-muted-foreground">참여자 정보</h3>
        {!readOnly && !editing && (
          <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
            편집
          </Button>
        )}
      </div>
      {editing ? (
        <form onSubmit={save} className="space-y-3">
          <FormField htmlFor="graph-person-name" label="이름" required>
            <Input
              id="graph-person-name"
              required
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
            />
          </FormField>
          <FormField htmlFor="graph-person-email" label="이메일">
            <Input
              id="graph-person-email"
              type="email"
              value={form.email}
              onChange={(event) => setForm({ ...form, email: event.target.value })}
            />
          </FormField>
          <FormField htmlFor="graph-person-role" label="역할">
            <Input
              id="graph-person-role"
              value={form.role}
              onChange={(event) => setForm({ ...form, role: event.target.value })}
            />
          </FormField>
          <FormField htmlFor="graph-person-aliases" label="별칭">
            <Input
              id="graph-person-aliases"
              value={form.aliases}
              onChange={(event) => setForm({ ...form, aliases: event.target.value })}
            />
          </FormField>
          <fieldset className="space-y-1">
            <legend className="font-medium">프로젝트</legend>
            {projects
              .filter((project) => !project.archivedAt || related.includes(project))
              .map((project) => (
                <label key={project.id} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={membership.includes(project.id)}
                    disabled={busy || Boolean(project.archivedAt)}
                    onChange={(event) =>
                      setMembership((current) =>
                        event.target.checked
                          ? [...current, project.id]
                          : current.filter((id) => id !== project.id),
                      )
                    }
                  />
                  {project.name}
                  {project.ownerPersonId === person.id ? " · 담당자" : ""}
                </label>
              ))}
          </fieldset>
          {error && (
            <p role="alert" className="text-destructive">
              {error}
            </p>
          )}
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={busy || !form.name.trim()}>
              저장
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => {
                setEditing(false);
                setError(undefined);
                setForm(personFormFrom(person));
                setMembership(
                  projects
                    .filter((project) => project.participantIds?.includes(person.id))
                    .map((project) => project.id),
                );
              }}
            >
              취소
            </Button>
          </div>
        </form>
      ) : (
        <dl className="space-y-1">
          <div>
            <dt className="inline text-muted-foreground">이름: </dt>
            <dd className="inline">{person.name}</dd>
          </div>
          <div>
            <dt className="inline text-muted-foreground">이메일: </dt>
            <dd className="inline">{person.email || "없음"}</dd>
          </div>
          <div>
            <dt className="inline text-muted-foreground">역할: </dt>
            <dd className="inline">{person.role || "없음"}</dd>
          </div>
          <div>
            <dt className="inline text-muted-foreground">별칭: </dt>
            <dd className="inline">{person.aliases.join(", ") || "없음"}</dd>
          </div>
          <div>
            <dt className="inline text-muted-foreground">프로젝트: </dt>
            <dd className="inline">
              {related
                .map(
                  (project) =>
                    `${project.name}${project.ownerPersonId === person.id ? " (담당자)" : ""}`,
                )
                .join(", ") || "없음"}
            </dd>
          </div>
        </dl>
      )}
    </section>
  );
}
