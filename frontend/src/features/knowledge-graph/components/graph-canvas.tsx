"use client";

import { useEffect, useRef } from "react";
import cytoscape, { type Core, type ElementDefinition, type NodeSingular } from "cytoscape";

import type { KnowledgeGraph } from "@/lib/api";

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
            "font-size": 11,
            "font-family": "inherit",
            "text-valign": "bottom",
            "text-margin-y": 6,
            width: (node: NodeSingular) => 22 + Number(node.data("degree") ?? 1) * 4,
            height: (node: NodeSingular) => 22 + Number(node.data("degree") ?? 1) * 4,
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
      layout: { name: "cose", animate: false, padding: 40, nodeRepulsion: () => 12000 },
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
    cy.layout({ name: "cose", animate: false, padding: 40, nodeRepulsion: () => 12000 }).run();
    cy.fit(undefined, 40);
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
