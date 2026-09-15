"use client";

import { use, useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { TimelineCard } from "@/features/context-timeline/components/timeline-card";
import {
  TimelineFilters,
  type TimelineFilterState,
} from "@/features/context-timeline/components/timeline-filters";
import { groupByDate } from "@/features/context-timeline/lib/group-by-date";
import { useAsync } from "@/hooks/use-async";
import { api } from "@/lib/api";
import type { ContextItemSource } from "@/lib/api";
import { workspacePath } from "@/lib/navigation";

export default function TimelinePage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const router = useRouter();

  const [filters, setFilters] = useState<TimelineFilterState>({ kinds: [], sourceKinds: [] });

  // 필터가 바뀌면 서버에 다시 물어봅니다. 항목 수가 커져도 같은 흐름으로 동작합니다.
  const kindsKey = filters.kinds.join(",");
  const sourceKindsKey = filters.sourceKinds.join(",");

  const { data, error, isLoading, reload } = useAsync(
    (signal) =>
      api.listContextItems(
        workspaceId,
        { kinds: filters.kinds, sourceKinds: filters.sourceKinds },
        signal,
      ),
    [workspaceId, kindsKey, sourceKindsKey],
  );

  const groups = useMemo(() => groupByDate(data ?? []), [data]);

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
    [router, workspaceId],
  );

  const openSuperseder = useCallback((contextItemId: string) => {
    document.getElementById(contextItemId)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  return (
    <>
      <PageHeader
        title="Context Timeline"
        description="결정과 이벤트가 쌓인 순서를 시간축으로 따라갑니다."
      />

      <TimelineFilters value={filters} onChange={setFilters} />

      <div className="mt-6">
        {isLoading ? (
          <div className="space-y-3">
            {[0, 1, 2].map((key) => (
              <Skeleton key={key} className="h-32 w-full rounded-xl" />
            ))}
          </div>
        ) : error ? (
          <div className="rounded-xl border border-border bg-card p-10 text-center">
            <p className="text-sm">{error.message}</p>
            <Button variant="outline" size="sm" className="mt-4" onClick={reload}>
              다시 시도
            </Button>
          </div>
        ) : groups.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
            조건에 맞는 맥락이 없습니다. 필터를 풀거나 소스를 더 올려보세요.
          </div>
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
                        className="absolute top-5 -left-[21px] size-2 rounded-full bg-border ring-4 ring-background"
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
