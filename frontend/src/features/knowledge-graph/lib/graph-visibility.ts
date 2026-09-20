import type { EntityType, GraphNode, KnowledgeGraph } from "@/lib/api";

import { entityLabel, entityTypes, materialLabel } from "./graph-style";

/**
 * 종류 칩으로 숨긴 노드인지 판단합니다. 캔버스·목록·상세 패널이 모두 이 함수를 씁니다.
 *
 * 회의·문서 자료 노드는 서버가 `event`로 보내지만 범례에서는 별도 칩("회의·문서 자료")이
 * 맡습니다. "이벤트"를 껐을 때 자료까지 사라지면 범례와 화면이 어긋나므로 제외합니다.
 */
export function isHiddenByType(
  node: Pick<GraphNode, "type" | "material">,
  hidden: readonly EntityType[],
): boolean {
  return !node.material && hidden.includes(node.type);
}

/**
 * 선택한 종류만 남기고, 한쪽 끝이 사라진 엣지도 함께 걸러냅니다.
 * 기준일을 골랐다면 그 시점에 아직 어떤 관계도 없던 노드는 숨깁니다(아직 없던 결정이 떠다니지 않게).
 *
 * 연결 여부는 종류를 숨기기 전의 그래프로 판단합니다. 그래서
 * `filterGraph(filterGraph(g, [], isolated), hidden, false)`와 `filterGraph(g, hidden, isolated)`가
 * 같고, 캔버스는 앞 단계의 그래프를 받아 종류만 `display: none`으로 가릴 수 있습니다.
 */
export function filterGraph(
  graph: KnowledgeGraph,
  hidden: readonly EntityType[],
  hideIsolated: boolean,
): KnowledgeGraph {
  if (hidden.length === 0 && !hideIsolated) return graph;

  const connected = new Set(graph.edges.flatMap((edge) => [edge.source, edge.target]));
  const nodes = graph.nodes.filter(
    (node) => !isHiddenByType(node, hidden) && (!hideIsolated || connected.has(node.id)),
  );
  const visible = new Set(nodes.map((node) => node.id));

  return {
    nodes,
    edges: graph.edges.filter((edge) => visible.has(edge.source) && visible.has(edge.target)),
  };
}

/**
 * 그래프의 구성(노드·엣지 id)이 같은지 비교할 서명입니다.
 *
 * 같은 구성을 다시 받았을 때는 배치를 다시 잡지 않습니다. 배치를 다시 잡으면 사용자가
 * 옮겨 둔 노드와 확대·이동 상태가 초기화됩니다.
 */
export function graphSignature(graph: KnowledgeGraph): string {
  const ids = (items: { id: string }[]) =>
    items
      .map((item) => item.id)
      .sort()
      .join("\u0001");
  return `${ids(graph.nodes)}\u0002${ids(graph.edges)}`;
}

export type GraphNodeGroup = {
  key: EntityType | "material";
  label: string;
  nodes: GraphNode[];
};

/**
 * "목록으로 보기"용으로 노드를 종류별로 묶습니다.
 *
 * 범례와 같은 순서이고, 빈 묶음은 빼며, 묶음 안에서는 이름순입니다.
 */
export function groupNodesByType(nodes: GraphNode[]): GraphNodeGroup[] {
  const byLabel = (a: GraphNode, b: GraphNode) => a.label.localeCompare(b.label, "ko");

  const groups: GraphNodeGroup[] = entityTypes.map((type) => ({
    key: type,
    label: entityLabel[type],
    nodes: nodes.filter((node) => !node.material && node.type === type).sort(byLabel),
  }));
  groups.push({
    key: "material",
    label: materialLabel,
    nodes: nodes.filter((node) => node.material).sort(byLabel),
  });

  return groups.filter((group) => group.nodes.length > 0);
}
