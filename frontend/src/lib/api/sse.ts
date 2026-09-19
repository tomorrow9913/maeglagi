/** Parses complete SSE frames and preserves an incomplete frame for the next network chunk. */
export function parseSseFrames(buffer: string): { payloads: string[]; remainder: string; done: boolean } {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const frames = normalized.split("\n\n");
  const remainder = frames.pop() ?? "";
  const payloads: string[] = [];
  for (const frame of frames) {
    const data = frame.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
    if (data === "[DONE]") return { payloads, remainder, done: true };
    if (data) payloads.push(data);
  }
  return { payloads, remainder, done: false };
}
