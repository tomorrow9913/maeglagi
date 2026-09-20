"use client";

import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { PageHeader } from "@/components/layout/page-header";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/common/state-views";
import { Button } from "@/components/ui/button";
import {
  CurrentStateCard,
  CurrentStateCardSkeleton,
} from "@/features/context-timeline/components/current-state-card";
import { TimelineCard } from "@/features/context-timeline/components/timeline-card";
import {
  TimelineFilters,
  type TimelineFilterState,
} from "@/features/context-timeline/components/timeline-filters";
import { groupByDate } from "@/features/context-timeline/lib/group-by-date";
import { kindDotClass } from "@/features/context-timeline/lib/kind-style";
import { useAsync } from "@/hooks/use-async";
import { useApi, useDemoMode, useWorkspacePath } from "@/lib/api/context";
import type { ContextItem, ContextItemSource } from "@/lib/api";
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

  const hasFilter = filters.kinds.length > 0 || filters.sourceKinds.length > 0;

  // 결과가 어떤 조건으로 받은 것인지 함께 들고 다닙니다. 재조회 중에는 이전 결과가 남아
  // 있어서, 지금의 필터 상태만 보고는 전체 목록인지 걸러진 목록인지 알 수 없습니다.
  const {
    data: result,
    error,
    isLoading,
    isRefetching,
    reload,
  } = useAsync(
    (signal) =>
      api
        .listContextItems(
          workspaceId,
          { kinds: filters.kinds, sourceKinds: filters.sourceKinds },
          signal,
        )
        .then((items) => ({ items, isFiltered: hasFilter })),
    [workspaceId, kindsKey, sourceKindsKey],
    { resetKey: workspaceId },
  );
  const data = result?.items;

  // 현재 상황 카드는 곁가지입니다. 못 받아도 타임라인은 그대로 보여주도록 오류는 무시합니다.
  const { data: contextStore, isLoading: isStoreLoading } = useAsync(
    (signal) => api.getContextStore(workspaceId, signal),
    [workspaceId],
    { resetKey: workspaceId },
  );

  /*
   * 대체 관계를 보여주려면 필터에 걸러진 항목의 제목도 필요합니다.
   *
   * 화면은 항상 필터 없이 열리므로 그때 받은 전체 목록을 기억해 둡니다. 요청을 두 배로
   * 늘리지 않으려는 것입니다. 전체 목록을 받기 전에 필터를 건 드문 경우에만, 빠진 제목이
   * 있을 때 한 번 더 받아 옵니다.
   */
  const [unfiltered, setUnfiltered] = useState<{ workspaceId: string; items: ContextItem[] }>();
  useEffect(() => {
    if (result && !result.isFiltered) setUnfiltered({ workspaceId, items: result.items });
  }, [result, workspaceId]);
  const knownItems = unfiltered?.workspaceId === workspaceId ? unfiltered.items : undefined;

  const needsTitleLookup = Boolean(
    result?.isFiltered &&
    !knownItems &&
    result.items.some(
      (item) => item.supersededBy && !result.items.some((other) => other.id === item.supersededBy),
    ),
  );
  const { data: lookedUp } = useAsync(
    (signal) =>
      needsTitleLookup ? api.listContextItems(workspaceId, {}, signal) : Promise.resolve(undefined),
    [workspaceId, needsTitleLookup],
    { resetKey: workspaceId },
  );
  useEffect(() => {
    if (lookedUp) setUnfiltered({ workspaceId, items: lookedUp });
  }, [lookedUp, workspaceId]);

  const groups = useMemo(() => groupByDate(data ?? []), [data]);

  const titleById = useMemo(
    () => new Map([...(knownItems ?? []), ...(data ?? [])].map((item) => [item.id, item.title])),
    [knownItems, data],
  );

  const openSource = useCallback(
    (source: Pick<ContextItemSource, "id" | "chunkId">) => {
      const query = new URLSearchParams({ source: source.id });
      if (source.chunkId) query.set("chunk", source.chunkId);
      router.push(`${workspacePath(workspaceId, "sources")}?${query.toString()}`);
    },
    [router, workspaceId, workspacePath],
  );
  const openSourceById = useCallback(
    (sourceId: string) => openSource({ id: sourceId }),
    [openSource],
  );

  /*
   * "이후 결정"으로 이동합니다. 화면만 스크롤하면 키보드와 스크린리더 사용자는 어디로
   * 왔는지 알 수 없으므로 초점을 카드로 옮기고 잠깐 강조합니다. 대상이 필터에 가려져
   * 있으면 필터를 풀고, 전체 목록이 도착한 뒤에 이동합니다.
   */
  const [pendingTargetId, setPendingTargetId] = useState<string>();
  const [highlightedId, setHighlightedId] = useState<string>();
  const highlightTimer = useRef<number | undefined>(undefined);

  const focusCard = useCallback((contextItemId: string): boolean => {
    const card = document
      .getElementById(contextItemId)
      ?.querySelector<HTMLElement>("[data-timeline-card]");
    if (!card) return false;

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    card.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "center" });
    card.focus({ preventScroll: true });

    setHighlightedId(contextItemId);
    window.clearTimeout(highlightTimer.current);
    highlightTimer.current = window.setTimeout(() => setHighlightedId(undefined), 2400);
    return true;
  }, []);
  useEffect(() => () => window.clearTimeout(highlightTimer.current), []);

  const openSuperseder = useCallback(
    (contextItemId: string) => {
      if (focusCard(contextItemId)) return;
      setPendingTargetId(contextItemId);
      setFilters({ kinds: [], sourceKinds: [] });
    },
    [focusCard],
  );

  useEffect(() => {
    // 필터를 푼 뒤의 전체 목록이 그려진 다음에만 찾습니다.
    if (!pendingTargetId || !result || result.isFiltered || isLoading) return;
    setPendingTargetId(undefined);
    if (!focusCard(pendingTargetId)) toast.error("이후 결정을 찾지 못했습니다.");
  }, [pendingTargetId, result, isLoading, focusCard]);

  return (
    <>
      <PageHeader
        title="Timeline"
        description="결정과 이벤트가 쌓인 순서를 시간축으로 따라갑니다."
      />

      {contextStore ? (
        <CurrentStateCard store={contextStore} onOpenSource={openSourceById} className="mb-6" />
      ) : isStoreLoading ? (
        <CurrentStateCardSkeleton className="mb-6" />
      ) : null}

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
                        isHighlighted={highlightedId === item.id}
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
