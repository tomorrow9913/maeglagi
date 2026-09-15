"use client";

import { ArrowRight, FileText, Mic } from "lucide-react";

import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import type { ContextItemSource, GraphNode, KnowledgeGraph } from "@/lib/api";

import { entityLabel, relationLabel } from "../lib/graph-style";

type Connection = {
  edgeId: string;
  relation: string;
  direction: "out" | "in";
  node: GraphNode;
};

function connectionsOf(graph: KnowledgeGraph, nodeId: string): Connection[] {
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));

  return graph.edges.flatMap<Connection>((edge) => {
    if (edge.source === nodeId) {
      const node = byId.get(edge.target);
      return node
        ? [{ edgeId: edge.id, relation: relationLabel[edge.type], direction: "out" as const, node }]
        : [];
    }
    if (edge.target === nodeId) {
      const node = byId.get(edge.source);
      return node
        ? [{ edgeId: edge.id, relation: relationLabel[edge.type], direction: "in" as const, node }]
        : [];
    }
    return [];
  });
}

/** 노드의 속성·연결·근거를 보여주는 사이드 패널입니다. */
export function NodeDetailSheet({
  graph,
  node,
  onClose,
  onSelectNode,
  onOpenSource,
}: {
  graph: KnowledgeGraph;
  node: GraphNode | undefined;
  onClose: () => void;
  onSelectNode: (nodeId: string) => void;
  onOpenSource: (source: ContextItemSource) => void;
}) {
  const connections = node ? connectionsOf(graph, node.id) : [];

  return (
    <Sheet open={Boolean(node)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full gap-0 sm:max-w-sm">
        {node ? (
          <>
            <SheetHeader>
              <SheetTitle>{node.label}</SheetTitle>
              <SheetDescription>
                {entityLabel[node.type]} · 연결 {node.degree}개
              </SheetDescription>
            </SheetHeader>

            <div className="space-y-6 overflow-y-auto px-4 pb-6">
              <section>
                <h3 className="mb-2 text-xs font-medium text-muted-foreground">속성</h3>
                <dl className="space-y-1.5 text-sm">
                  <div className="flex gap-3">
                    <dt className="w-16 shrink-0 text-muted-foreground">종류</dt>
                    <dd>
                      <StatusBadge tone="neutral">{entityLabel[node.type]}</StatusBadge>
                    </dd>
                  </div>
                  <div className="flex gap-3">
                    <dt className="w-16 shrink-0 text-muted-foreground">ID</dt>
                    <dd className="font-mono text-xs break-all text-muted-foreground">{node.id}</dd>
                  </div>
                </dl>
              </section>

              <section>
                <h3 className="mb-2 text-xs font-medium text-muted-foreground">
                  연결 ({connections.length})
                </h3>
                {connections.length === 0 ? (
                  <p className="text-sm text-muted-foreground">연결된 항목이 없습니다.</p>
                ) : (
                  <ul className="space-y-1">
                    {connections.map((connection) => (
                      <li key={connection.edgeId}>
                        <button
                          type="button"
                          onClick={() => onSelectNode(connection.node.id)}
                          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent"
                        >
                          <span className="shrink-0 text-xs text-muted-foreground">
                            {connection.direction === "out"
                              ? connection.relation
                              : `←${connection.relation}`}
                          </span>
                          <span className="truncate">{connection.node.label}</span>
                          <ArrowRight
                            className="ml-auto size-3 shrink-0 text-muted-foreground"
                            aria-hidden
                          />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section>
                <h3 className="mb-2 text-xs font-medium text-muted-foreground">근거</h3>
                {node.sources.length === 0 ? (
                  <p className="text-sm text-muted-foreground">연결된 근거가 없습니다.</p>
                ) : (
                  <ul className="space-y-2">
                    {node.sources.map((source) => {
                      const Icon = source.kind === "meeting" ? Mic : FileText;
                      return (
                        <li key={`${source.id}-${source.chunkId ?? ""}`}>
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-auto w-full justify-start gap-2 py-2 text-left"
                            onClick={() => onOpenSource(source)}
                          >
                            <Icon className="size-3.5 shrink-0" aria-hidden />
                            <span className="truncate text-xs">{source.title}</span>
                          </Button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>
            </div>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
