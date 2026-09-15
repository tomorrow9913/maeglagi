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
  person: "--chart-1",
  project: "--chart-2",
  decision: "--chart-3",
  task: "--chart-4",
  event: "--chart-5",
};

export type GraphPalette = Record<EntityType | "edge" | "text" | "muted", string>;

/**
 * 디자인 토큰에서 실제 색 값을 읽어옵니다.
 *
 * cytoscape는 캔버스에 그리므로 `var(--chart-1)`을 해석하지 못합니다.
 * 토큰을 단일 출처로 유지하려고 런타임에 계산된 값을 한 번 읽어 넘깁니다.
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
    edge: read("--border", "#d9ddd8"),
    text: read("--foreground", "#1c2b26"),
    muted: read("--muted-foreground", "#66736e"),
  };
}
