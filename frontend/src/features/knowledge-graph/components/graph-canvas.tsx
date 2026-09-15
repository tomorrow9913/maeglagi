"use client";

import { useEffect, useRef } from "react";
import cytoscape, { type Core, type ElementDefinition, type NodeSingular } from "cytoscape";

import type { KnowledgeGraph } from "@/lib/api";

/**
 * 노드가 적어도 캔버스를 채우도록 간격을 넓게 잡습니다.
 * 간격이 좁으면 fit()이 크게 확대하고, 라벨까지 함께 확대돼 서로 겹칩니다.
 */
const LAYOUT = {
  name: "cose" as const,
  animate: false,
  padding: 48,
  nodeRepulsion: () => 400_000,
  idealEdgeLength: () => 150,
  nodeOverlap: 24,
  gravity: 60,
};

/** 라벨이 읽기 어려워지지 않는 선의 초기 확대 배율 */
const MAX_INITIAL_ZOOM = 1.25;

import { readGraphPalette, relationLabel } from "../lib/graph-style";

/**
 * Knowledge Graph를 캔버스에 그립니다.
 *
 * 확대·축소·드래그는 cytoscape가 처리하고, 이 컴포넌트는 데이터가 바뀔 때
 * 요소만 교체합니다. 노드 색은 디자인 토큰에서 읽어 옵니다.
 */
export function GraphCanvas({
  graph,
  selectedNodeId,
  onSelectNode,
}: {
  graph: KnowledgeGraph;
  selectedNodeId?: string;
  onSelectNode: (nodeId: string | undefined) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core>(null);

  // 콜백 변경으로 그래프를 다시 만들지 않도록 참조만 유지합니다.
  const selectRef = useRef(onSelectNode);
  selectRef.current = onSelectNode;

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
              palette[node.data("type") as keyof typeof palette],
            label: "data(label)",
            color: palette.text,
            "font-size": 12,
            "font-weight": 500,
            "text-valign": "bottom",
            "text-margin-y": 8,
            "text-wrap": "wrap",
            "text-max-width": "110px",
            "text-background-color": "#ffffff",
            "text-background-opacity": 0.85,
            "text-background-padding": "3px",
            "text-background-shape": "roundrectangle",
            width: (node: NodeSingular) => 26 + Number(node.data("degree") ?? 1) * 5,
            height: (node: NodeSingular) => 26 + Number(node.data("degree") ?? 1) * 5,
            "border-width": 0,
          },
        },
        {
          selector: "node:selected",
          style: { "border-width": 3, "border-color": palette.text, "border-opacity": 0.35 },
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
            "font-size": 9,
            color: palette.muted,
            "text-background-color": "#ffffff",
            "text-background-opacity": 0.75,
            "text-background-padding": "2px",
          },
        },
      ],
      layout: LAYOUT,
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
    };
  }, []);

  // 데이터가 바뀌면 요소만 갈아끼우고 레이아웃을 다시 잡습니다.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    const elements: ElementDefinition[] = [
      ...graph.nodes.map((node) => ({
        data: { id: node.id, label: node.label, type: node.type, degree: node.degree },
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
    cy.layout(LAYOUT).run();
    cy.fit(undefined, 48);

    /*
     * cytoscape는 라벨도 줌 배율만큼 확대합니다. 노드가 적으면 fit이 크게
     * 확대해 라벨이 서로 겹치므로, 확대 배율에 상한을 둡니다.
     */
    if (cy.zoom() > MAX_INITIAL_ZOOM) {
      cy.zoom(MAX_INITIAL_ZOOM);
      cy.center();
    }
  }, [graph]);

  // 사이드 패널에서 선택이 바뀌어도 캔버스 강조가 따라오게 합니다.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    cy.nodes().unselect();
    if (selectedNodeId) cy.getElementById(selectedNodeId).select();
  }, [selectedNodeId, graph]);

  return (
    <div ref={containerRef} className="size-full" role="application" aria-label="지식 그래프" />
  );
}
