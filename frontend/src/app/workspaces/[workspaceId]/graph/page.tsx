"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/layout/page-header";
import { ErrorState } from "@/components/common/state-views";
import { Skeleton } from "@/components/ui/skeleton";
import { GraphCanvas } from "@/features/knowledge-graph/components/graph-canvas";
import { NodeDetailSheet } from "@/features/knowledge-graph/components/node-detail-sheet";
import {
  entityLabel,
  readGraphPalette,
  type GraphPalette,
} from "@/features/knowledge-graph/lib/graph-style";
import { useAsync } from "@/hooks/use-async";
import { api } from "@/lib/api";
import type { ContextItemSource, EntityType, KnowledgeGraph } from "@/lib/api";
import { workspacePath } from "@/lib/navigation";
import { cn } from "@/lib/utils";

const entityTypes: EntityType[] = ["person", "project", "decision", "task", "event"];

/** 선택한 종류만 남기고, 한쪽 끝이 사라진 엣지도 함께 걸러냅니다. */
function filterGraph(graph: KnowledgeGraph, hidden: EntityType[]): KnowledgeGraph {
  if (hidden.length === 0) return graph;

  const nodes = graph.nodes.filter((node) => !hidden.includes(node.type));
  const visible = new Set(nodes.map((node) => node.id));

  return {
    nodes,
    edges: graph.edges.filter((edge) => visible.has(edge.source) && visible.has(edge.target)),
  };
}

export default function GraphPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const router = useRouter();

  const [hidden, setHidden] = useState<EntityType[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string>();

  // 토큰 값은 브라우저에서만 읽을 수 있어 마운트 후 한 번만 가져옵니다.
  const [palette, setPalette] = useState<GraphPalette>();
  useEffect(() => setPalette(readGraphPalette()), []);

  const { data, error, isLoading, reload } = useAsync(
    (signal) => api.getKnowledgeGraph(workspaceId, signal),
    [workspaceId],
  );

  const graph = useMemo(
    () => filterGraph(data ?? { nodes: [], edges: [] }, hidden),
    [data, hidden],
  );
  const selectedNode = useMemo(
    () => graph.nodes.find((node) => node.id === selectedNodeId),
    [graph, selectedNodeId],
  );

  const openSource = useCallback(
    (source: ContextItemSource) => {
      const query = new URLSearchParams({ source: source.id });
      if (source.chunkId) query.set("chunk", source.chunkId);
      router.push(`${workspacePath(workspaceId, "sources")}?${query.toString()}`);
    },
    [router, workspaceId],
  );

  return (
    <>
      <PageHeader
        title="Knowledge Graph"
        description="사람·프로젝트·업무의 연결을 그래프로 탐색합니다. 노드를 누르면 상세가 열립니다."
      />

      <div className="flex flex-wrap items-center gap-1.5">
        {entityTypes.map((type) => {
          const isVisible = !hidden.includes(type);

          return (
            <button
              key={type}
              type="button"
              aria-pressed={isVisible}
              onClick={() =>
                setHidden((current) =>
                  current.includes(type)
                    ? current.filter((entry) => entry !== type)
                    : [...current, type],
                )
              }
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors",
                isVisible
                  ? "border-border text-foreground"
                  : "border-border text-muted-foreground/60 line-through",
              )}
            >
              <span
                aria-hidden
                className="size-2 rounded-full"
                style={palette ? { backgroundColor: palette[type] } : undefined}
              />
              {entityLabel[type]}
            </button>
          );
        })}
      </div>

      <div className="mt-4 h-[min(70vh,620px)] overflow-hidden rounded-xl border border-border bg-card">
        {isLoading ? (
          <Skeleton className="size-full rounded-none" />
        ) : error ? (
          <ErrorState
            error={error}
            onRetry={reload}
            className="size-full justify-center border-0"
          />
        ) : graph.nodes.length === 0 ? (
          <div className="flex size-full items-center justify-center p-10 text-center text-sm text-muted-foreground">
            {hidden.length > 0
              ? "선택한 종류의 노드가 없습니다. 필터를 풀어보세요."
              : "표시할 노드가 없습니다. 회의나 문서를 올리면 관계가 만들어집니다."}
          </div>
        ) : (
          <GraphCanvas
            graph={graph}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
          />
        )}
      </div>

      <p className="mt-2 text-xs text-muted-foreground">
        휠로 확대·축소, 드래그로 이동합니다. 노드를 끌어 위치를 바꿀 수 있습니다.
      </p>

      <NodeDetailSheet
        graph={graph}
        node={selectedNode}
        onClose={() => setSelectedNodeId(undefined)}
        onSelectNode={setSelectedNodeId}
        onOpenSource={openSource}
      />
    </>
  );
}
