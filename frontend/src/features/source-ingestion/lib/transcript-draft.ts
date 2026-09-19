export type TranscriptSegment = { id: number; text: string; isFinal: boolean };

export type TranscriptTurn = TranscriptSegment & { speaker: string; edited?: boolean };

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
