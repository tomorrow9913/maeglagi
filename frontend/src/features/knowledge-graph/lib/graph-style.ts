import type { EntityType, RelationType } from "@/lib/api";

/** 범례와 목록이 같은 순서를 쓰도록 한 곳에 둡니다. */
export const entityTypes: EntityType[] = ["person", "project", "decision", "task", "event"];

/**
 * entity 종류의 화면 이름입니다.
 *
 * `person`은 "사람"입니다(brand.md의 제품 정의: 사람·프로젝트·결정·업무·이벤트). 회의와
 * 문서에서 뽑아낸 이름 전체를 가리키고, 그중 워크스페이스에 등록한 사람만
 * "참여자·프로젝트" 화면의 "참여자"입니다. 두 말을 섞지 않습니다.
 */
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

/** 원문 자료(회의·문서) 노드의 화면 이름. 서버는 이 노드도 `event`로 보내므로 `material`로 구분합니다. */
export const materialLabel = "회의·문서 자료";

/**
 * 색만으로 종류를 구분하지 않도록 종류마다 모양을 고정합니다.
 *
 * 값은 cytoscape의 `shape` 이름이고, 범례(`NodeShapeIcon`)가 같은 모양을 그립니다.
 * 둘이 어긋나면 범례가 거짓말을 하게 되므로 여기 한 곳에서만 정합니다.
 */
export type NodeShape =
  "ellipse" | "round-rectangle" | "diamond" | "hexagon" | "round-triangle" | "rectangle";

export const entityShape: Record<EntityType, NodeShape> = {
  person: "ellipse",
  project: "round-rectangle",
  decision: "diamond",
  task: "hexagon",
  event: "round-triangle",
};

export const materialShape: NodeShape = "rectangle";

/** DOM에 그리는 범례·목록용 색. 캔버스와 달리 CSS 변수를 그대로 쓸 수 있습니다. */
export const entityColorVar: Record<EntityType, string> = {
  person: "var(--chart-1)",
  project: "var(--chart-2)",
  decision: "var(--chart-3)",
  task: "var(--chart-4)",
  event: "var(--chart-5)",
};

/** 자료 노드는 추출된 엔티티가 아니라서 chart 색 대신 보조 글자색을 씁니다. 캔버스의 `palette.muted`와 같은 값입니다. */
export const materialColorVar = "var(--muted-foreground)";

/** 범례·목록에서 한 종류를 그릴 때 쓰는 모양과 색 */
export function nodeLook(key: EntityType | "material"): { shape: NodeShape; color: string } {
  return key === "material"
    ? { shape: materialShape, color: materialColorVar }
    : { shape: entityShape[key], color: entityColorVar[key] };
}

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

export type GraphPalette = Record<EntityType | "edge" | "text" | "muted" | "surface", string>;

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
    person: read(tokenByEntity.person, "#30785d"),
    project: read(tokenByEntity.project, "#3a6ea7"),
    decision: read(tokenByEntity.decision, "#a6552d"),
    task: read(tokenByEntity.task, "#795ea7"),
    event: read(tokenByEntity.event, "#816b21"),
    edge: read("--border-hex", "#dedad0"),
    text: read("--foreground-hex", "#1c2b26"),
    muted: read("--muted-foreground-hex", "#5d6b65"),
    // 라벨 배경. 캔버스를 감싼 카드 면과 같은 색이어야 떠 보이지 않습니다.
    surface: read("--card-hex", "#fffdf9"),
  };
}
