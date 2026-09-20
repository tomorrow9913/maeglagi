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
import type {
  ContextItemSource,
  GraphNode,
  KnowledgeGraph,
  WorkspacePerson,
  WorkspaceProject,
} from "@/lib/api";
import { PersonDirectoryDetails } from "./person-directory-details";

import { entityLabel, materialLabel } from "../lib/graph-style";
import { relationTail } from "../lib/relation-sentence";

type Connection = {
  edgeId: string;
  /** 상대 이름 뒤에 붙는 말. 이름과 이어 읽으면 "홍길동이 참여" 같은 문장이 됩니다. */
  tail: string;
  node: GraphNode;
};

function connectionsOf(graph: KnowledgeGraph, nodeId: string): Connection[] {
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));

  return graph.edges.flatMap<Connection>((edge) => {
    const direction = edge.source === nodeId ? "out" : edge.target === nodeId ? "in" : undefined;
    if (!direction) return [];

    const other = byId.get(direction === "out" ? edge.target : edge.source);
    const source = byId.get(edge.source);
    if (!other || !source) return [];

    return [
      {
        edgeId: edge.id,
        tail: relationTail({
          relation: edge.type,
          direction,
          sourceType: source.type,
          otherLabel: other.label,
        }),
        node: other,
      },
    ];
  });
}

/** 노드의 속성·연결·근거를 보여주는 사이드 패널입니다. */
export function NodeDetailSheet({
  graph,
  node,
  onClose,
  onSelectNode,
  onOpenSource,
  onOpenDirectory,
  isReadOnly = false,
  workspaceId,
  person,
  projects,
  personLoading,
  personError,
  onPersonSaved,
}: {
  graph: KnowledgeGraph;
  node: GraphNode | undefined;
  onClose: () => void;
  onSelectNode: (nodeId: string) => void;
  onOpenSource: (source: ContextItemSource) => void;
  onOpenDirectory: (node: GraphNode) => void;
  /** 데모처럼 참여자·프로젝트를 편집할 수 없는 화면인지 */
  isReadOnly?: boolean;
  workspaceId: string;
  person?: WorkspacePerson;
  projects: WorkspaceProject[];
  personLoading: boolean;
  personError?: Error;
  onPersonSaved: () => void;
}) {
  const connections = node ? connectionsOf(graph, node.id) : [];
  const typeLabel = node ? (node.material ? materialLabel : entityLabel[node.type]) : "";

  return (
    <Sheet open={Boolean(node)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full gap-0 sm:max-w-sm">
        {node ? (
          <>
            <SheetHeader>
              <SheetTitle>{node.label}</SheetTitle>
              <SheetDescription>
                {typeLabel} · 연결 {node.degree}개
              </SheetDescription>
            </SheetHeader>

            <div className="space-y-6 overflow-y-auto px-4 pb-6">
              {node.directoryKind === "Person" && node.directoryId ? (
                person ? (
                  <PersonDirectoryDetails
                    key={`${workspaceId}:${person.id}:${person.updatedAt}:${projects.map((project) => `${project.id}:${project.revision}`).join(",")}`}
                    workspaceId={workspaceId}
                    person={person}
                    projects={projects}
                    readOnly={isReadOnly}
                    onSaved={onPersonSaved}
                  />
                ) : (
                  <p className="text-sm text-muted-foreground" role="status">
                    {personError
                      ? "참여자 정보를 불러오지 못했습니다."
                      : personLoading
                        ? "참여자 정보를 불러오는 중"
                        : "등록된 참여자 정보가 없습니다."}
                  </p>
                )
              ) : null}
              {node.material && node.sourceId ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    onOpenSource({
                      id: node.sourceId!,
                      kind: node.kind === "Meeting" ? "meeting" : "document",
                      title: node.label,
                    })
                  }
                >
                  자료 원문 열기
                </Button>
              ) : null}
              {/* 화면 이름은 메뉴와 같은 "참여자·프로젝트"입니다. 데모에서는 편집할 수 없으므로 "보기"로 씁니다. */}
              {node.directoryId &&
              (node.directoryKind === "Person" || node.directoryKind === "Project") ? (
                <Button variant="outline" size="sm" onClick={() => onOpenDirectory(node)}>
                  {isReadOnly ? "참여자·프로젝트에서 보기" : "참여자·프로젝트에서 편집"}
                </Button>
              ) : null}
              <section>
                <h3 className="mb-2 text-xs font-medium text-muted-foreground">속성</h3>
                <dl className="space-y-1.5 text-sm">
                  <div className="flex gap-3">
                    <dt className="w-16 shrink-0 text-muted-foreground">종류</dt>
                    <dd>
                      <StatusBadge tone="neutral">{typeLabel}</StatusBadge>
                    </dd>
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
                          {/* 이름과 꼬리를 붙여 한 문장으로 읽히게 합니다. 이름만 말줄임합니다. */}
                          <span className="flex min-w-0 items-baseline">
                            <span className="truncate">{connection.node.label}</span>
                            <span className="shrink-0 whitespace-pre text-muted-foreground">
                              {connection.tail}
                            </span>
                          </span>
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
