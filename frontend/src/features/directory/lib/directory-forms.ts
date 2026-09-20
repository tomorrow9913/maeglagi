import type { WorkspacePerson, WorkspaceProject } from "@/lib/api";

export type PersonForm = { name: string; email: string; aliases: string; role: string };

export type ProjectForm = {
  name: string;
  goal: string;
  description: string;
  ownerPersonId: string;
  participantIds: string[];
  startsOn: string;
  endsOn: string;
};

export const emptyPerson: PersonForm = { name: "", email: "", aliases: "", role: "" };

export const emptyProject: ProjectForm = {
  name: "",
  goal: "",
  description: "",
  ownerPersonId: "",
  participantIds: [],
  startsOn: "",
  endsOn: "",
};

/** 편집 폼은 항상 원본에서 다시 만듭니다. 취소한 입력이 다음 편집에 남지 않게 하려는 것입니다. */
export function personFormFrom(person: WorkspacePerson): PersonForm {
  return {
    name: person.name,
    email: person.email ?? "",
    aliases: person.aliases.join(", "),
    role: person.role ?? "",
  };
}

export function projectFormFrom(project: WorkspaceProject): ProjectForm {
  return {
    name: project.name,
    goal: project.goal ?? "",
    description: project.description ?? "",
    ownerPersonId: project.ownerPersonId ?? "",
    participantIds: project.participantIds ?? [],
    startsOn: project.startsOn ?? "",
    endsOn: project.endsOn ?? "",
  };
}

/** 쉼표로 구분한 별칭 입력을 목록으로 바꿉니다. */
export function parseAliases(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

/** 저장 버튼을 말없이 막지 않도록, 기간이 뒤집혔을 때 보여줄 문구를 돌려줍니다. */
export function projectDateError(
  form: Pick<ProjectForm, "startsOn" | "endsOn">,
): string | undefined {
  return form.startsOn && form.endsOn && form.endsOn < form.startsOn
    ? "종료일은 시작일 이후여야 합니다."
    : undefined;
}

/**
 * 닫기 전에 확인할 만큼 입력이 바뀌었는지 봅니다.
 *
 * 앞뒤 공백만 다른 것은 바뀐 것으로 치지 않고, 참여자 목록은 순서를 무시합니다.
 */
export function isFormDirty<T extends PersonForm | ProjectForm>(current: T, initial: T): boolean {
  const normalize = (value: unknown) =>
    Array.isArray(value) ? JSON.stringify([...value].sort()) : String(value ?? "").trim();

  return (Object.keys(initial) as (keyof T)[]).some(
    (key) => normalize(current[key]) !== normalize(initial[key]),
  );
}
