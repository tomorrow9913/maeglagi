"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import cytoscape, { type Core, type ElementDefinition, type NodeSingular } from "cytoscape";
import { Maximize, Minus, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type { EntityType, KnowledgeGraph } from "@/lib/api";

import { entityShape, materialShape, readGraphPalette, relationLabel } from "../lib/graph-style";
import { graphSignature, isHiddenByType } from "../lib/graph-visibility";

/**
 * 노드가 적어도 캔버스를 채우도록 간격을 넓게 잡습니다.
 *
 * 간격이 좁으면 fit()이 크게 확대하고, 라벨까지 함께 확대돼 서로 겹칩니다.
 * 라벨은 노드 아래 가운데 정렬이라 가로로 가까운 노드끼리 특히 부딪히므로,
 * 노드 간 반발력을 라벨 폭(`LABEL_MAX_WIDTH`)보다 넉넉하게 둡니다.
 */
const LAYOUT = {
  name: "cose" as const,
  animate: false,
  padding: 56,
  nodeRepulsion: () => 900_000,
  idealEdgeLength: () => 210,
  nodeOverlap: 40,
  gravity: 45,
};

/** 라벨이 읽기 어려워지지 않는 선의 초기 확대 배율 */
const MAX_INITIAL_ZOOM = 1.25;

/** 버튼 한 번에 바뀌는 확대 배율 */
const ZOOM_STEP = 1.3;

/**
 * 이 수를 넘으면 배치 계산이 눈에 띄게 오래 걸립니다. 계산은 메인 스레드를 막으므로
 * 먼저 안내를 그린 다음에 시작합니다.
 */
const LARGE_GRAPH_NODE_COUNT = 120;

/**
 * 라벨 한 줄의 최대 폭.
 *
 * 좁힐수록 여러 줄로 접혀 가로 폭이 줄고, 옆 노드의 라벨과 부딪힐 확률이
 * 낮아집니다. 세 어절짜리 항목 이름이 두 줄로 접히는 선입니다.
 */
const LABEL_MAX_WIDTH = "82px";

const HIDDEN_CLASS = "type-hidden";

/**
 * 지금 보이는 노드와 그 사이의 엣지입니다.
 *
 * cytoscape의 `:visible`은 스타일 계산 결과를 캐시해서, 클래스를 바꾼 직후(다음 프레임을
 * 그리기 전)에는 이전 값을 돌려줄 수 있습니다. 그래서 스타일이 아니라 클래스로 고릅니다.
 */
function visibleElements(cy: Core) {
  const nodes = cy.nodes().not(`.${HIDDEN_CLASS}`);
  return nodes.union(nodes.edgesWith(nodes));
}

function nodeSize(node: NodeSingular): number {
  return 26 + Number(node.data("degree") ?? 1) * 5;
}

/**
 * Knowledge Graph를 캔버스에 그립니다.
 *
 * 확대·축소·드래그는 cytoscape가 처리합니다. 이 컴포넌트는 그래프의 구성이 바뀔 때만
 * 요소를 교체하고 배치를 다시 잡습니다. 종류 칩으로 숨기는 것은 요소를 지우지 않고
 * `display: none`으로 가리기만 해서, 옮겨 둔 노드와 확대·이동 상태가 유지됩니다.
 */
export function GraphCanvas({
  graph,
  hiddenTypes,
  selectedNodeId,
  onSelectNode,
}: {
  /** 종류 필터를 적용하기 전의 그래프 */
  graph: KnowledgeGraph;
  /** 범례에서 끈 종류. 해당 노드와 거기에 붙은 엣지를 가립니다. */
  hiddenTypes: readonly EntityType[];
  selectedNodeId?: string;
  onSelectNode: (nodeId: string | undefined) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core>(null);
  const signatureRef = useRef<string | undefined>(undefined);
  const [isLayingOut, setIsLayingOut] = useState(false);

  // 콜백 변경으로 그래프를 다시 만들지 않도록 참조만 유지합니다.
  const selectRef = useRef(onSelectNode);
  selectRef.current = onSelectNode;
  // 요소를 새로 넣을 때 숨긴 종류를 처음부터 가려 두려고 읽습니다. 바뀔 때의 처리는 아래 effect가 맡습니다.
  const hiddenTypesRef = useRef(hiddenTypes);
  hiddenTypesRef.current = hiddenTypes;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const palette = readGraphPalette();

    const cy = cytoscape({
      container,
      style: [
        {
          selector: "node",
          style: {
            "background-color": (node: NodeSingular) =>
              node.data("material")
                ? palette.muted
                : palette[node.data("type") as keyof typeof palette],
            // 색만으로 종류를 구분하지 않도록 모양도 종류마다 다릅니다. 범례와 같은 표를 씁니다.
            shape: (node: NodeSingular) =>
              node.data("material") ? materialShape : entityShape[node.data("type") as EntityType],
            label: "data(label)",
            color: palette.text,
            "font-size": 12,
            "font-weight": 500,
            "text-valign": "bottom",
            "text-margin-y": 10,
            "text-wrap": "wrap",
            "text-max-width": LABEL_MAX_WIDTH,
            /*
             * 라벨 배경을 불투명하게 깔고 테두리를 둡니다. 노드를 끌어다
             * 겹쳐 놓아도 어느 글자가 어느 라벨인지 구분됩니다.
             */
            "text-background-color": palette.surface,
            "text-background-opacity": 1,
            "text-background-padding": "4px",
            "text-background-shape": "roundrectangle",
            "text-border-width": 1,
            "text-border-color": palette.edge,
            "text-border-opacity": 1,
            // 자료 노드는 문서처럼 가로로 긴 사각형입니다.
            width: (node: NodeSingular) => nodeSize(node) * (node.data("material") ? 1.2 : 1),
            height: (node: NodeSingular) => nodeSize(node) * (node.data("material") ? 0.8 : 1),
            "border-width": 0,
          },
        },
        {
          selector: "node:selected",
          style: { "border-width": 3, "border-color": palette.text, "border-opacity": 0.35 },
        },
        /*
         * 포커스 모드. 노드를 고르면 직접 연결된 이웃만 남기고 나머지를 흐립니다.
         * 노드가 많아져도 지금 보고 있는 관계만 읽히게 하려는 것입니다.
         */
        {
          selector: ".faded",
          style: { opacity: 0.15, "text-opacity": 0 },
        },
        // 범례에서 끈 종류. 노드를 가리면 cytoscape가 거기에 붙은 엣지도 함께 가립니다.
        {
          selector: `node.${HIDDEN_CLASS}`,
          style: { display: "none" },
        },
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": palette.edge,
            "target-arrow-color": palette.edge,
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.8,
            "curve-style": "bezier",
            label: "data(label)",
            "font-size": 10,
            color: palette.muted,
            /*
             * 선을 따라 눕혀 노드 라벨과 부딪히는 면적을 줄입니다.
             * 가로로 놓으면 노드 아래 라벨과 같은 방향이라 자주 겹칩니다.
             */
            "text-rotation": "autorotate",
            "text-background-color": palette.surface,
            "text-background-opacity": 1,
            "text-background-padding": "3px",
            "text-background-shape": "roundrectangle",
          },
        },
      ],
      minZoom: 0.3,
      maxZoom: 3,
      wheelSensitivity: 0.2,
    });

    cy.on("tap", "node", (event) => selectRef.current(event.target.id()));
    // 빈 곳을 누르면 선택을 해제합니다.
    cy.on("tap", (event) => {
      if (event.target === cy) selectRef.current(undefined);
    });

    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
      signatureRef.current = undefined;
    };
  }, []);

  /** 보이는 요소가 캔버스에 다 들어오게 맞춥니다. */
  const fitToView = useCallback(() => {
    const cy = cyRef.current;
    if (!cy) return;

    const visible = visibleElements(cy);
    if (visible.empty()) return;

    cy.fit(visible, 48);
    /*
     * cytoscape는 라벨도 줌 배율만큼 확대합니다. 노드가 적으면 fit이 크게
     * 확대해 라벨이 서로 겹치므로, 확대 배율에 상한을 둡니다.
     */
    if (cy.zoom() > MAX_INITIAL_ZOOM) {
      cy.zoom(MAX_INITIAL_ZOOM);
      cy.center(visible);
    }
  }, []);

  // 그래프의 구성이 바뀌면 요소를 갈아끼우고 배치를 다시 잡습니다.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    const signature = graphSignature(graph);
    if (signature === signatureRef.current) {
      // 같은 구성을 다시 받았습니다. 이름과 연결 수만 갱신하고 배치·확대는 그대로 둡니다.
      cy.batch(() => {
        for (const node of graph.nodes) {
          cy.getElementById(node.id).data({ label: node.label, degree: node.degree });
        }
      });
      return;
    }
    signatureRef.current = signature;

    const elements: ElementDefinition[] = [
      ...graph.nodes.map((node) => ({
        data: {
          id: node.id,
          label: node.label,
          type: node.type,
          degree: node.degree,
          material: Boolean(node.material),
        },
        // 숨긴 종류도 배치에는 넣어 자리를 잡아 둡니다. 다시 켰을 때 제자리에 나타납니다.
        classes: isHiddenByType(node, hiddenTypesRef.current) ? HIDDEN_CLASS : undefined,
      })),
      ...graph.edges.map((edge) => ({
        data: {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          label: relationLabel[edge.type],
        },
      })),
    ];

    cy.elements().remove();
    cy.add(elements);

    const runLayout = () => {
      const projects = cy.nodes('[type = "project"]');
      cy.layout(
        projects.length
          ? {
              name: "breadthfirst",
              directed: false,
              roots: projects.toArray().map((node) => node.id()),
              spacingFactor: 1.4,
              padding: 56,
            }
          : LAYOUT,
      ).run();
      fitToView();
    };

    if (graph.nodes.length < LARGE_GRAPH_NODE_COUNT) {
      runLayout();
      return;
    }

    /*
     * 큰 그래프의 배치 계산은 메인 스레드를 막습니다. 안내를 먼저 그릴 수 있도록
     * 두 프레임을 양보한 뒤에 시작합니다(첫 프레임에 상태가 반영되고, 둘째에 그려집니다).
     */
    setIsLayingOut(true);
    let isDone = false;
    let second = 0;
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => {
        if (cyRef.current === cy) runLayout();
        isDone = true;
        setIsLayingOut(false);
      });
    });
    return () => {
      if (isDone) return;
      cancelAnimationFrame(first);
      cancelAnimationFrame(second);
      setIsLayingOut(false);
      // 배치를 마치지 못했으므로 다음에 같은 구성을 받아도 다시 잡게 합니다.
      signatureRef.current = undefined;
    };
  }, [graph, fitToView]);

  // 종류 칩은 요소를 지우지 않고 가리기만 합니다. 배치와 확대·이동 상태가 유지됩니다.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    cy.batch(() => {
      cy.nodes().forEach((node) => {
        const hidden = isHiddenByType(
          { type: node.data("type"), material: node.data("material") },
          hiddenTypes,
        );
        node.toggleClass(HIDDEN_CLASS, hidden);
      });
    });
  }, [hiddenTypes, graph]);

  // 사이드 패널에서 선택이 바뀌어도 캔버스 강조와 포커스 모드가 따라오게 합니다.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    cy.batch(() => {
      cy.nodes().unselect();
      cy.elements().removeClass("faded");
      if (!selectedNodeId) return;

      const selected = cy.getElementById(selectedNodeId);
      if (selected.empty()) return;

      selected.select();
      cy.elements().difference(selected.closedNeighborhood()).addClass("faded");
    });
  }, [selectedNodeId, graph]);

  const zoomBy = (factor: number) => {
    const cy = cyRef.current;
    if (!cy) return;
    // 화면 가운데를 기준으로 확대합니다. 기준을 주지 않으면 그래프 원점 쪽으로 밀려납니다.
    cy.zoom({
      level: cy.zoom() * factor,
      renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 },
    });
  };

  return (
    <div className="relative size-full">
      {/*
       * 캔버스 안은 마우스와 터치로만 다룰 수 있어 보조 기술에는 그림으로 알립니다.
       * 같은 노드는 화면의 "목록으로 보기"에서 키보드로 열 수 있습니다.
       */}
      <div
        ref={containerRef}
        className="size-full"
        role="img"
        aria-label="지식 그래프. 같은 내용을 목록으로 보기에서 키보드로 살펴볼 수 있습니다."
      />

      {/* 휠과 핀치 없이도 확대·축소할 수 있게 합니다. 터치 화면에서는 캔버스가 스크롤 제스처를 가져갑니다. */}
      <div className="absolute right-3 bottom-3 flex flex-col gap-1 rounded-lg border border-border bg-card p-1 shadow-xs">
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="확대"
          title="확대"
          onClick={() => zoomBy(ZOOM_STEP)}
        >
          <Plus aria-hidden />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="축소"
          title="축소"
          onClick={() => zoomBy(1 / ZOOM_STEP)}
        >
          <Minus aria-hidden />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="전체 보기"
          title="전체 보기"
          onClick={fitToView}
        >
          <Maximize aria-hidden />
        </Button>
      </div>

      {isLayingOut ? (
        <div
          role="status"
          className="absolute inset-0 flex items-center justify-center gap-2 bg-card text-sm text-muted-foreground"
        >
          <Spinner />
          그래프를 배치하는 중
        </div>
      ) : null}
    </div>
  );
}
