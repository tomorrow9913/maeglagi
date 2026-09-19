import type { MeetingUtterance, WorkspacePerson, WorkspaceProject } from "@/lib/api";
import type { TranscriptTurn } from "./transcript-draft";

export type MeetingSpeaker = { id: string; name: string };

export function nextLocalSpeakerName(speakers: MeetingSpeaker[]): string {
  const usedNumbers = new Set(speakers.map((speaker) => /^화자 ([1-9]\d*)$/.exec(speaker.name.trim())?.[1]).filter(Boolean).map(Number));
  let number = 1;
  while (usedNumbers.has(number)) number += 1;
  return `화자 ${number}`;
}

/** Keep one directory identity when several projects contain the same person. */
export function projectRoster(projectIds: string[], projects: WorkspaceProject[], people: WorkspacePerson[]): WorkspacePerson[] {
  const ids = new Set(projects.filter((project) => projectIds.includes(project.id) && !project.archivedAt).flatMap((project) => [
    ...(project.ownerPersonId ? [project.ownerPersonId] : []),
    ...(project.participantIds ?? []),
  ]));
  const emails = new Set<string>();
  return people.filter((person) => {
    if (!ids.has(person.id) || person.archivedAt) return false;
    const email = person.email?.trim().toLowerCase();
    if (email && emails.has(email)) return false;
    if (email) emails.add(email);
    return true;
  });
}

export function addRoster(speakers: MeetingSpeaker[], roster: WorkspacePerson[], directory: WorkspacePerson[] = roster): MeetingSpeaker[] {
  const seen = new Set(speakers.map((speaker) => speaker.id));
  const seenEmails = new Set(directory.filter((person) => seen.has(person.id)).map((person) => person.email?.trim().toLowerCase()).filter(Boolean));
  const next = [...speakers];
  for (const person of roster) {
    const email = person.email?.trim().toLowerCase();
    if (seen.has(person.id) || (email && seenEmails.has(email))) continue;
    next.push({ id: person.id, name: person.name });
    seen.add(person.id);
    if (email) seenEmails.add(email);
  }
  return next;
}

export function removeSpeaker(
  speakers: MeetingSpeaker[],
  rows: TranscriptTurn[],
  currentSpeaker: string,
  removedId: string,
  replacementId: string,
): { speakers: MeetingSpeaker[]; rows: TranscriptTurn[]; currentSpeaker: string; reassigned: number; replacement: MeetingSpeaker | null } {
  const index = speakers.findIndex((speaker) => speaker.id === removedId);
  if (index < 0) {
    return { speakers, rows, currentSpeaker, reassigned: 0, replacement: null };
  }
  const reassigned = rows.filter((row) => row.speaker === removedId).length;
  const needsReplacement = reassigned > 0 || currentSpeaker === removedId || speakers.length === 1;
  if (!needsReplacement) {
    return { speakers: speakers.filter((speaker) => speaker.id !== removedId), rows, currentSpeaker, reassigned: 0, replacement: null };
  }
  const replacement = { id: replacementId, name: nextLocalSpeakerName(speakers) };
  const nextRows = rows.map((row) => row.speaker === removedId
    ? { ...row, speaker: replacementId, personId: null }
    : row);
  const nextSpeakers = speakers.filter((speaker) => speaker.id !== removedId);
  nextSpeakers.splice(index, 0, replacement);
  const nextCurrent = currentSpeaker === removedId ? replacementId : currentSpeaker;
  return { speakers: nextSpeakers, rows: nextRows, currentSpeaker: nextCurrent, reassigned, replacement };
}

export function meetingUtterances(rows: TranscriptTurn[], speakers: MeetingSpeaker[], people: WorkspacePerson[]): MeetingUtterance[] {
  return rows.map((row) => {
    const speaker = speakers.find((item) => item.id === row.speaker);
    const person = people.find((item) => item.id === row.speaker);
    return {
      id: String(row.id),
      personId: person?.id ?? null,
      speakerName: speaker?.name.trim() || person?.name || "화자 1",
      text: row.text,
      startSeconds: row.startSeconds ?? null,
      endSeconds: row.endSeconds ?? null,
    };
  });
}
