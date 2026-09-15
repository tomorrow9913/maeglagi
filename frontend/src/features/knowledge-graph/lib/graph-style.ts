import type { EntityType, RelationType } from "@/lib/api";

export const entityLabel: Record<EntityType, string> = {
  person: "사람",
  project: "프로젝트",
  decision: "결정",
  task: "업무",
  event: "이벤트",
};

export const relationLabel: Record<RelationType, string> = {
  participates_in: "참여",
  decided: "결정함",
  assigned_to: "담당",
  blocks: "막음",
  relates_to: "관련",
  supersedes: "대체",
};

/**
 * entity 종류와 chart 토큰의 대응.
 *
 * globals.css의 `--chart-1..5` 주석과 같은 순서를 유지해야 합니다.
 */
const tokenByEntity: Record<EntityType, string> = {
  person: "--chart-1-hex",
  project: "--chart-2-hex",
  decision: "--chart-3-hex",
  task: "--chart-4-hex",
  event: "--chart-5-hex",
};

export type GraphPalette = Record<EntityType | "edge" | "text" | "muted", string>;

/**
 * 디자인 토큰에서 실제 색 값을 읽어옵니다.
 *
 * cytoscape는 캔버스에 그리므로 `var(--chart-1)`을 해석하지 못하고, oklch()
 * 문자열도 읽지 못합니다. 그래서 globals.css에 함께 정의해 둔 `*-hex`
 * 토큰을 읽습니다.
 */
export function readGraphPalette(): GraphPalette {
  const styles = getComputedStyle(document.documentElement);
  const read = (token: string, fallback: string) =>
    styles.getPropertyValue(token).trim() || fallback;

  return {
    person: read(tokenByEntity.person, "#3e715f"),
    project: read(tokenByEntity.project, "#3b6ea5"),
    decision: read(tokenByEntity.decision, "#c2703f"),
    task: read(tokenByEntity.task, "#7a5ea8"),
    event: read(tokenByEntity.event, "#9a8d5a"),
    edge: read("--border-hex", "#d9ddd8"),
    text: read("--foreground-hex", "#1c2b26"),
    muted: read("--muted-foreground-hex", "#66736e"),
  };
}
