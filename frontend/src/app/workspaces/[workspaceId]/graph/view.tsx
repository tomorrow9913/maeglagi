"use client";

import { use, useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/layout/page-header";
import { EmptyState, ErrorState } from "@/components/common/state-views";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { List, Network } from "lucide-react";

import { GraphCanvas } from "@/features/knowledge-graph/components/graph-canvas";
import { GraphNodeList } from "@/features/knowledge-graph/components/graph-node-list";
import { NodeDetailSheet } from "@/features/knowledge-graph/components/node-detail-sheet";
import { NodeShapeIcon } from "@/features/knowledge-graph/components/node-shape-icon";
import {
  entityLabel,
  entityTypes,
  materialLabel,
  nodeLook,
} from "@/features/knowledge-graph/lib/graph-style";
import { filterGraph } from "@/features/knowledge-graph/lib/graph-visibility";
import { useAsync } from "@/hooks/use-async";
import { useApi, useDemoMode, useWorkspacePath } from "@/lib/api/context";
import type { ContextItemSource, EntityType } from "@/lib/api";
import { cn } from "@/lib/utils";

const EMPTY_GRAPH = { nodes: [], edges: [] };

const chipClass = (isOn: boolean) =>
  cn(
    "inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1 text-xs transition-colors",
    isOn ? "text-foreground" : "text-muted-foreground line-through",
  );

export default function GraphPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  return <GraphView workspaceId={workspaceId} />;
}

export function GraphView({ workspaceId }: { workspaceId: string }) {
  const api = useApi();
  const router = useRouter();
  const workspacePath = useWorkspacePath();
  const isDemo = useDemoMode();

  const [hidden, setHidden] = useState<EntityType[]>([]);
  const [showMaterials, setShowMaterials] = useState(true);
  // 비우면 지금 유효한 관계, 날짜를 고르면 그날 유효했던 관계를 보여줍니다.
  const [asOf, setAsOf] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState<string>();
  // 캔버스는 마우스·터치 전용이라, 같은 노드를 키보드로 열 수 있는 목록을 함께 둡니다.
  const [viewMode, setViewMode] = useState<"canvas" | "list">("canvas");

  const { data, error, isLoading, isRefetching, reload } = useAsync(
    (signal) =>
      api.getKnowledgeGraph(
        workspaceId,
        { ...(asOf ? { at: asOf } : {}), includeMaterials: showMaterials },
        signal,
      ),
    [workspaceId, asOf, showMaterials],
    { resetKey: workspaceId },
  );

  /*
   * 두 단계로 거릅니다. 캔버스는 종류 필터를 적용하기 전의 `baseGraph`를 받아 숨긴 종류를
   * 가리기만 하고(배치와 확대 상태 유지), 목록과 상세 패널은 실제로 보이는 `graph`를 씁니다.
   */
  const baseGraph = useMemo(
    () => filterGraph(data ?? EMPTY_GRAPH, [], Boolean(asOf)),
    [data, asOf],
  );
  const graph = useMemo(() => filterGraph(baseGraph, hidden, false), [baseGraph, hidden]);
  const selectedNode = useMemo(
    () => graph.nodes.find((node) => node.id === selectedNodeId),
    [graph, selectedNodeId],
  );
  const personId = selectedNode?.directoryKind === "Person" ? selectedNode.directoryId : undefined;
  const directory = useAsync(
    async (signal) => {
      if (!personId) return { people: [], projects: [] };
      const [people, projects] = await Promise.all([
        api.listPeople(workspaceId, signal),
        api.listProjects(workspaceId, signal),
      ]);
      return { people, projects };
    },
    [api, workspaceId, personId],
    { resetKey: `${workspaceId}:${personId ?? ""}` },
  );

  const openSource = useCallback(
    (source: ContextItemSource) => {
      const query = new URLSearchParams({ source: source.id });
      if (source.chunkId) query.set("chunk", source.chunkId);
      router.push(`${workspacePath(workspaceId, "sources")}?${query.toString()}`);
    },
    [router, workspaceId, workspacePath],
  );

  const isCanvasCovered = graph.nodes.length === 0 || viewMode === "list";

  const filterEmptyState = (
    <EmptyState
      className="size-full justify-center border-0"
      title="선택한 종류의 노드가 없습니다"
      description="필터를 해제하면 다른 종류의 노드를 볼 수 있어요."
      action={
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setHidden([]);
            setShowMaterials(true);
          }}
        >
          필터 해제
        </Button>
      }
    />
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
        <button
          type="button"
          aria-pressed={showMaterials}
          onClick={() => setShowMaterials((shown) => !shown)}
          className={chipClass(showMaterials)}
        >
          <NodeShapeIcon {...nodeLook("material")} />
          {materialLabel}
        </button>
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
              className={chipClass(isVisible)}
            >
              {/* 캔버스의 노드와 같은 모양·색입니다. 색을 구분하기 어려워도 모양으로 읽을 수 있습니다. */}
              <NodeShapeIcon {...nodeLook(type)} />
              {entityLabel[type]}
            </button>
          );
        })}

        <Button
          type="button"
          variant="outline"
          size="sm"
          className="ml-auto"
          onClick={() => setViewMode((mode) => (mode === "list" ? "canvas" : "list"))}
        >
          {viewMode === "list" ? <Network aria-hidden /> : <List aria-hidden />}
          {viewMode === "list" ? "그래프로 보기" : "목록으로 보기"}
        </Button>
      </div>

      {/* 기준일·자료 토글로 다시 받을 때는 캔버스를 유지합니다. 언마운트하면 확대와 배치가 초기화됩니다. */}
      <div
        className={cn(
          "relative mt-4 h-[min(70vh,620px)] overflow-hidden rounded-xl border border-border bg-card transition-opacity",
          isRefetching && "opacity-60",
        )}
        aria-busy={isLoading}
      >
        {isRefetching ? (
          <p role="status" className="sr-only">
            그래프를 다시 불러오는 중
          </p>
        ) : null}
        {isLoading && !data ? (
          <div role="status" className="size-full">
            <span className="sr-only">그래프를 불러오는 중</span>
            <Skeleton className="size-full rounded-none" aria-hidden />
          </div>
        ) : error ? (
          <ErrorState
            error={error}
            onRetry={reload}
            className="size-full justify-center border-0"
          />
        ) : baseGraph.nodes.length === 0 ? (
          // 왜 비었는지에 따라 다음 행동이 다릅니다: 자료 토글, 기준일, 아직 소스가 없는 경우.
          !showMaterials ? (
            filterEmptyState
          ) : asOf ? (
            <EmptyState
              className="size-full justify-center border-0"
              title={`${asOf}에는 유효한 관계가 없습니다`}
              description="다른 날짜를 고르거나 지금 시점으로 돌아가 보세요."
              action={
                <Button variant="outline" size="sm" onClick={() => setAsOf("")}>
                  지금으로
                </Button>
              }
            />
          ) : (
            <EmptyState
              className="size-full justify-center border-0"
              title="표시할 노드가 없습니다"
              description="회의나 문서를 올리면 관계가 만들어져요."
              action={
                isDemo ? null : (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => router.push(workspacePath(workspaceId, "sources"))}
                  >
                    소스 올리러 가기
                  </Button>
                )
              }
            />
          )
        ) : (
          <>
            {/*
             * 목록이나 빈 상태를 보여줄 때도 캔버스는 그대로 둡니다. 언마운트하면 옮겨 둔
             * 노드와 확대 상태가 사라집니다. 가려진 동안에는 `inert`로 초점과 읽기를 막습니다.
             */}
            <div className="size-full" inert={isCanvasCovered}>
              <GraphCanvas
                graph={baseGraph}
                hiddenTypes={hidden}
                selectedNodeId={selectedNode?.id}
                onSelectNode={setSelectedNodeId}
              />
            </div>
            {graph.nodes.length === 0 ? (
              <div className="absolute inset-0 bg-card">{filterEmptyState}</div>
            ) : viewMode === "list" ? (
              <GraphNodeList
                className="absolute inset-0 bg-card"
                nodes={graph.nodes}
                selectedNodeId={selectedNode?.id}
                onSelectNode={setSelectedNodeId}
              />
            ) : null}
          </>
        )}
      </div>

      <NodeDetailSheet
        graph={graph}
        node={selectedNode}
        onClose={() => setSelectedNodeId(undefined)}
        onSelectNode={setSelectedNodeId}
        onOpenSource={openSource}
        onOpenDirectory={(node) =>
          router.push(
            `${workspacePath(workspaceId, "directory")}?${node.directoryKind === "Person" ? "person" : "project"}=${encodeURIComponent(node.directoryId ?? "")}`,
          )
        }
        isReadOnly={isDemo}
        workspaceId={workspaceId}
        person={directory.data?.people.find((item) => item.id === personId)}
        projects={directory.data?.projects ?? []}
        personLoading={Boolean(personId) && directory.isLoading && !directory.data}
        personError={personId ? directory.error : undefined}
        onPersonSaved={() => {
          directory.reload();
          reload();
        }}
      />
    </>
  );
}
