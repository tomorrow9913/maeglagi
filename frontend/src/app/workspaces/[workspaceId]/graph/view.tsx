"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/layout/page-header";
import { ErrorState } from "@/components/common/state-views";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { GraphCanvas } from "@/features/knowledge-graph/components/graph-canvas";
import { NodeDetailSheet } from "@/features/knowledge-graph/components/node-detail-sheet";
import {
  entityLabel,
  readGraphPalette,
  type GraphPalette,
} from "@/features/knowledge-graph/lib/graph-style";
import { useAsync } from "@/hooks/use-async";
import { useApi, useWorkspacePath } from "@/lib/api/context";
import type { ContextItemSource, EntityType, KnowledgeGraph } from "@/lib/api";
import { cn } from "@/lib/utils";

const entityTypes: EntityType[] = ["person", "project", "decision", "task", "event"];

/**
 * 선택한 종류만 남기고, 한쪽 끝이 사라진 엣지도 함께 걸러냅니다.
 * 기준일을 골랐다면 그 시점에 아직 어떤 관계도 없던 노드는 숨깁니다(아직 없던 결정이 떠다니지 않게).
 */
function filterGraph(
  graph: KnowledgeGraph,
  hidden: EntityType[],
  hideIsolated: boolean,
): KnowledgeGraph {
  if (hidden.length === 0 && !hideIsolated) return graph;

  const connected = new Set(graph.edges.flatMap((edge) => [edge.source, edge.target]));
  const nodes = graph.nodes.filter(
    (node) => !hidden.includes(node.type) && (!hideIsolated || connected.has(node.id)),
  );
  const visible = new Set(nodes.map((node) => node.id));

  return {
    nodes,
    edges: graph.edges.filter((edge) => visible.has(edge.source) && visible.has(edge.target)),
  };
}

export default function GraphPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  return <GraphView workspaceId={workspaceId} />;
}

export function GraphView({ workspaceId }: { workspaceId: string }) {
  const api = useApi();
  const router = useRouter();
  const workspacePath = useWorkspacePath();

  const [hidden, setHidden] = useState<EntityType[]>([]);
  const [showMaterials, setShowMaterials] = useState(true);
  // 비우면 지금 유효한 관계, 날짜를 고르면 그날 유효했던 관계를 보여줍니다.
  const [asOf, setAsOf] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState<string>();

  // 토큰 값은 브라우저에서만 읽을 수 있어 마운트 후 한 번만 가져옵니다.
  const [palette, setPalette] = useState<GraphPalette>();
  useEffect(() => setPalette(readGraphPalette()), []);

  const { data, error, isLoading, reload } = useAsync(
    (signal) => api.getKnowledgeGraph(workspaceId, { ...(asOf ? { at: asOf } : {}), includeMaterials: showMaterials }, signal),
    [workspaceId, asOf, showMaterials],
  );

  const graph = useMemo(
    () => filterGraph(data ?? { nodes: [], edges: [] }, hidden, Boolean(asOf)),
    [data, hidden, asOf],
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
    [router, workspaceId, workspacePath],
  );

  return (
    <>
      <PageHeader title="Graph" description="사람·프로젝트·업무의 연결을 그래프로 탐색합니다." />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label htmlFor="graph-as-of" className="text-xs font-medium text-muted-foreground">
          기준일
        </label>
        <Input
          id="graph-as-of"
          type="date"
          value={asOf}
          onChange={(event) => setAsOf(event.target.value)}
          className="h-8 w-40 text-xs"
        />
        {asOf ? (
          <Button type="button" variant="ghost" size="sm" onClick={() => setAsOf("")}>
            지금으로
          </Button>
        ) : null}
        <span className="text-xs text-muted-foreground">
          {asOf
            ? `${asOf}에 유효했던 관계만 보여줍니다.`
            : "지금 유효한 관계를 보여줍니다. 날짜를 고르면 그때의 관계를 볼 수 있어요."}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <button type="button" aria-pressed={showMaterials} onClick={() => setShowMaterials((shown) => !shown)} className={cn("inline-flex items-center rounded-full border px-3 py-1 text-xs", showMaterials ? "border-border text-foreground" : "border-border text-muted-foreground/60 line-through")}>회의·문서 자료</button>
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
              : "표시할 노드가 없습니다. 회의나 문서를 올리면 관계가 만들어져요."}
          </div>
        ) : (
          <GraphCanvas
            graph={graph}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
          />
        )}
      </div>

      <NodeDetailSheet
        graph={graph}
        node={selectedNode}
        onClose={() => setSelectedNodeId(undefined)}
        onSelectNode={setSelectedNodeId}
        onOpenSource={openSource}
        onOpenDirectory={(node) => router.push(`${workspacePath(workspaceId, "directory")}?${node.directoryKind === "Person" ? "person" : "project"}=${encodeURIComponent(node.directoryId ?? "")}`)}
      />
    </>
  );
}
