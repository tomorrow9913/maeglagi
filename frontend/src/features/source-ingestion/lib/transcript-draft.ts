export type TranscriptSegment = { id: number; text: string; isFinal: boolean; startSeconds?: number | null; endSeconds?: number | null };

export type TranscriptTurn = TranscriptSegment & {
  speaker: string;
  /** Keeps an existing directory reference even when the person was later archived. */
  personId?: string | null;
  edited?: boolean;
  startSeconds?: number | null;
  endSeconds?: number | null;
};

type ReviewPerson = { id: string; name: string; archivedAt: string | null };
type ReviewSpeaker = { id: string; name: string };

/** Existing person references remain attached until a row is explicitly reassigned. */
export function unresolvedReviewPeople(rows: TranscriptTurn[], people: ReviewPerson[]): number[] {
  return rows.filter((row) => {
    const person = people.find((item) => item.id === row.speaker);
    return Boolean(person?.archivedAt || (row.personId && row.speaker === row.personId && !person));
  }).map((row) => row.id);
}

export function reviewUtterances(
  rows: TranscriptTurn[],
  people: ReviewPerson[],
  speakers: ReviewSpeaker[],
  ids: Map<number, string>,
) {
  return rows.map((row) => {
    const person = people.find((item) => item.id === row.speaker);
    const speaker = speakers.find((item) => item.id === row.speaker);
    return {
      id: ids.get(row.id) ?? `manual-${Math.abs(row.id)}`,
      personId: person?.id ?? (row.speaker === row.personId ? row.personId : null) ?? null,
      speakerName: person?.name || speaker?.name || "화자 1",
      text: row.text,
      startSeconds: row.startSeconds ?? null,
      endSeconds: row.endSeconds ?? null,
    };
  });
}

export function mergeTranscript(
  current: TranscriptTurn[],
  incoming: TranscriptSegment[],
  activeSpeaker: string,
): TranscriptTurn[] {
  const updates = new Map(incoming.map((segment) => [segment.id, segment]));
  const existingIds = new Set(current.map((row) => row.id));
  const rows: TranscriptTurn[] = [];

  for (const row of current) {
    const update = updates.get(row.id);
    if (row.id < 0) {
      rows.push({ ...row });
    } else if (update) {
      rows.push({
        ...row,
        text: row.edited ? row.text : update.text,
        isFinal: update.isFinal,
        startSeconds: row.startSeconds ?? update.startSeconds,
        endSeconds: update.endSeconds ?? row.endSeconds,
      });
    } else if (row.edited || row.isFinal) {
      rows.push({ ...row });
    }
  }

  for (const segment of incoming) {
    if (!existingIds.has(segment.id)) {
      rows.push({ ...segment, speaker: activeSpeaker });
      existingIds.add(segment.id);
    }
  }

  return rows;
}

export function serializeTranscript(rows: TranscriptTurn[], speakers: string[]): string {
  return rows
    .map((row) => {
      const text = row.text.trim();
      if (!text) return "";
      const index = Number(row.speaker);
      const name =
        Number.isInteger(index) && index >= 0
          ? speakers[index]?.trim() || `화자 ${index + 1}`
          : row.speaker.trim() || "화자 1";
      return `${name}: ${text}`;
    })
    .filter(Boolean)
    .join("\n\n");
}
