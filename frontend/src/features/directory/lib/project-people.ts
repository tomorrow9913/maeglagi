import type { WorkspacePerson, WorkspaceProject } from "@/lib/api";

/** Keep the owner visible even when they are not a participant or are archived. */
export function listProjectPeople(project: WorkspaceProject, people: WorkspacePerson[]) {
  const ids = new Set([
    ...(project.ownerPersonId ? [project.ownerPersonId] : []),
    ...(project.participantIds ?? []),
  ]);
  const peopleById = new Map(people.map((person) => [person.id, person]));
  return [...ids].map((id) => ({
    id,
    person: peopleById.get(id),
    isOwner: id === project.ownerPersonId,
  }));
}
