"use client";

import type { GraphNode } from "@/lib/api";
import { cn } from "@/lib/utils";

import { nodeLook } from "../lib/graph-style";
import { groupNodesByType } from "../lib/graph-visibility";
import { NodeShapeIcon } from "./node-shape-icon";

/**
 * 그래프와 같은 노드를 종류별 목록으로 보여줍니다.
 *
 * 캔버스는 마우스와 터치로만 다룰 수 있습니다. 키보드와 스크린리더로도 모든 노드의
 * 상세를 열 수 있도록, 같은 `onSelectNode`를 부르는 버튼 목록을 따로 둡니다.
 */
export function GraphNodeList({
  nodes,
  selectedNodeId,
  onSelectNode,
  className,
}: {
  /** 지금 캔버스에 보이는 노드 (숨긴 종류는 제외) */
  nodes: GraphNode[];
  selectedNodeId?: string;
  onSelectNode: (nodeId: string) => void;
  className?: string;
}) {
  const groups = groupNodesByType(nodes);

  return (
    <div className={cn("overflow-y-auto p-4", className)}>
      <div className="grid gap-x-6 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
        {groups.map((group) => {
          const headingId = `graph-list-${group.key}`;
          const { shape, color } = nodeLook(group.key);

          return (
            <section key={group.key} aria-labelledby={headingId} className="min-w-0">
              <h3
                id={headingId}
                className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground"
              >
                <NodeShapeIcon shape={shape} color={color} />
                {group.label} <span className="tabular-nums">{group.nodes.length}</span>
              </h3>
              <ul className="mt-1.5 space-y-0.5">
                {group.nodes.map((node) => (
                  <li key={node.id}>
                    <button
                      type="button"
                      aria-current={node.id === selectedNodeId ? "true" : undefined}
                      onClick={() => onSelectNode(node.id)}
                      className={cn(
                        "flex w-full items-baseline gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors outline-none hover:bg-accent focus-visible:ring-3 focus-visible:ring-ring/50",
                        node.id === selectedNodeId && "bg-accent text-accent-foreground",
                      )}
                    >
                      <span className="min-w-0 flex-1 truncate">{node.label}</span>
                      <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                        연결 {node.degree}개
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </div>
  );
}
