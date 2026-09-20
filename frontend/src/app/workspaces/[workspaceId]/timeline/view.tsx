"use client";

import { use, useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/layout/page-header";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/common/state-views";
import { Button } from "@/components/ui/button";
import { CurrentStateCard } from "@/features/context-timeline/components/current-state-card";
import { TimelineCard } from "@/features/context-timeline/components/timeline-card";
import {
  TimelineFilters,
  type TimelineFilterState,
} from "@/features/context-timeline/components/timeline-filters";
import { groupByDate } from "@/features/context-timeline/lib/group-by-date";
import { kindDotClass } from "@/features/context-timeline/lib/kind-style";
import { useAsync } from "@/hooks/use-async";
import { useApi, useDemoMode, useWorkspacePath } from "@/lib/api/context";
import type { ContextItemSource } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function TimelinePage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  return <TimelineView workspaceId={workspaceId} />;
}

export function TimelineView({ workspaceId }: { workspaceId: string }) {
  const api = useApi();
  const router = useRouter();
  const workspacePath = useWorkspacePath();
  const isDemo = useDemoMode();

  const [filters, setFilters] = useState<TimelineFilterState>({ kinds: [], sourceKinds: [] });

  // 필터가 바뀌면 서버에 다시 물어봅니다. 항목 수가 커져도 같은 흐름으로 동작합니다.
  const kindsKey = filters.kinds.join(",");
  const sourceKindsKey = filters.sourceKinds.join(",");

  const { data, error, isLoading, isRefetching, reload } = useAsync(
    (signal) =>
      api.listContextItems(
        workspaceId,
        { kinds: filters.kinds, sourceKinds: filters.sourceKinds },
        signal,
      ),
    [workspaceId, kindsKey, sourceKindsKey],
    { resetKey: workspaceId },
  );

  // 현재 상황 카드는 곁가지입니다. 못 받아도 타임라인은 그대로 보여주도록 오류는 무시합니다.
  const { data: contextStore } = useAsync(
    (signal) => api.getContextStore(workspaceId, signal),
    [workspaceId],
  );

  const groups = useMemo(() => groupByDate(data ?? []), [data]);
  const hasFilter = filters.kinds.length > 0 || filters.sourceKinds.length > 0;

  // 대체 관계를 보여주려면 필터에 걸러진 항목의 제목도 필요합니다.
  const titleById = useMemo(
    () => new Map((data ?? []).map((item) => [item.id, item.title])),
    [data],
  );

  const openSource = useCallback(
    (source: ContextItemSource) => {
      const query = new URLSearchParams({ source: source.id });
      if (source.chunkId) query.set("chunk", source.chunkId);
      router.push(`${workspacePath(workspaceId, "sources")}?${query.toString()}`);
    },
    [router, workspaceId, workspacePath],
  );

  const openSuperseder = useCallback((contextItemId: string) => {
    document.getElementById(contextItemId)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  return (
    <>
      <PageHeader
        title="Timeline"
        description="결정과 이벤트가 쌓인 순서를 시간축으로 따라갑니다."
      />

      {contextStore ? <CurrentStateCard store={contextStore} className="mb-6" /> : null}

      <TimelineFilters value={filters} onChange={setFilters} />

      {/* 필터를 바꿀 때는 목록을 비우지 않고 흐리게만 둡니다. 스켈레톤은 첫 로드에만 씁니다. */}
      <div
        className={cn("mt-6 transition-opacity", isRefetching && "opacity-60")}
        aria-busy={isLoading}
      >
        {isLoading && !data ? (
          <ListSkeleton count={3} className="h-32" label="Timeline을 불러오는 중" />
        ) : error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : groups.length === 0 ? (
          <EmptyState
            title={hasFilter ? "조건에 맞는 맥락이 없습니다" : "아직 쌓인 맥락이 없습니다"}
            description={
              hasFilter
                ? "필터를 해제하면 더 많은 항목을 볼 수 있어요."
                : "회의나 문서를 올리면 결정과 이벤트가 여기에 쌓여요."
            }
            action={
              hasFilter ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setFilters({ kinds: [], sourceKinds: [] })}
                >
                  필터 해제
                </Button>
              ) : isDemo ? null : (
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
        ) : (
          <ol className="space-y-8">
            {groups.map((group) => (
              <li key={group.date}>
                <h2 className="sticky top-14 z-10 -mx-1 bg-background/85 px-1 py-2 text-xs font-medium text-muted-foreground backdrop-blur">
                  {group.label}
                </h2>
                <ul className="space-y-3 border-l border-border pl-4">
                  {group.items.map((item) => (
                    <li key={item.id} id={item.id} className="relative">
                      <span
                        aria-hidden
                        className={cn(
                          "absolute top-5 -left-5 size-2 rounded-full ring-4 ring-background",
                          item.supersededBy ? "bg-border" : kindDotClass[item.kind],
                        )}
                      />
                      <TimelineCard
                        item={item}
                        supersededByTitle={
                          item.supersededBy ? titleById.get(item.supersededBy) : undefined
                        }
                        onOpenSource={openSource}
                        onOpenSuperseder={openSuperseder}
                      />
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        )}
      </div>
    </>
  );
}
