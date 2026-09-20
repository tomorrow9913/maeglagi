import { Skeleton } from "@/components/ui/skeleton";
import type { ContextStore, ContextStoreItem } from "@/lib/api";
import { localDateKey } from "@/lib/format-date";
import { cn } from "@/lib/utils";

/**
 * 시각이 붙은 값만 현지 날짜로 바꿉니다.
 *
 * 결정일·기한처럼 날짜만 있는 값(`2026-09-11`)은 시간대가 없는 달력 날짜입니다.
 * `Date`로 해석하면 UTC 자정이 되어 서쪽 시간대에서 하루 앞당겨지므로 그대로 둡니다.
 */
function formatDate(value: string): string {
  return value.length <= 10 ? value : localDateKey(value);
}

function Column({
  title,
  items,
  detail,
  onOpenSource,
}: {
  title: string;
  items: ContextStoreItem[];
  /** 항목 아래에 덧붙일 한 줄 (담당자·기한·결정일). 없으면 설명을 씁니다. */
  detail: (item: ContextStoreItem) => string;
  onOpenSource?: (sourceId: string) => void;
}) {
  return (
    <section aria-label={title} className="min-w-0">
      <h3 className="text-xs font-medium text-muted-foreground">
        {title} <span className="tabular-nums">{items.length}</span>
      </h3>
      {items.length === 0 ? (
        <p className="mt-1.5 text-sm text-muted-foreground">없음</p>
      ) : (
        <ul className="mt-1.5 space-y-2">
          {items.map((item, index) => {
            const line = detail(item);
            const body = (
              <>
                <span className="font-medium">{item.title}</span>
                {line ? (
                  <span className="mt-0.5 block text-xs text-muted-foreground">{line}</span>
                ) : null}
              </>
            );
            const sourceId = item.sourceId;

            return (
              // 제목은 겹칠 수 있어 순서를 함께 키로 씁니다.
              <li key={`${item.title}-${index}`} className="text-sm">
                {sourceId && onOpenSource ? (
                  <button
                    type="button"
                    onClick={() => onOpenSource(sourceId)}
                    aria-label={`${item.title} · 근거 원문 열기`}
                    className="-mx-1.5 block w-[calc(100%+0.75rem)] rounded-md px-1.5 py-1 text-left transition-colors outline-none hover:bg-accent/60 focus-visible:ring-3 focus-visible:ring-ring/50"
                  >
                    {body}
                  </button>
                ) : (
                  <div className="py-1">{body}</div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/**
 * 프로젝트의 현재 상황(Context Store)입니다.
 *
 * Timeline이 "무슨 일이 있었나"라면 이 카드는 "지금 어디까지 왔나"를 답합니다.
 * 이미 대체된 결정과 해결된 이슈는 여기서 빠지고, 지난 기록은 아래 타임라인에 남습니다.
 */
export function CurrentStateCard({
  store,
  onOpenSource,
  className,
}: {
  store: ContextStore;
  /** 항목의 근거 소스를 엽니다. 넘기지 않으면 항목은 글자로만 보입니다. */
  onOpenSource?: (sourceId: string) => void;
  className?: string;
}) {
  return (
    <section
      aria-label="현재 상황"
      className={cn("rounded-xl border border-border bg-card p-4", className)}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 className="text-sm font-medium">현재 상황</h2>
        <span className="text-xs text-muted-foreground">
          소스 {store.sourceIds.length}개 반영 ·{" "}
          <time dateTime={store.updatedAt}>{formatDate(store.updatedAt)}</time> 갱신
        </span>
      </div>

      {store.currentState ? (
        <p className="mt-2 text-sm leading-relaxed whitespace-pre-line">{store.currentState}</p>
      ) : null}

      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        <Column
          title="유효한 결정"
          items={store.decisions}
          detail={(item) =>
            item.decidedAt ? `${formatDate(item.decidedAt)} 결정` : item.description
          }
          onOpenSource={onOpenSource}
        />
        <Column
          title="열린 이슈"
          items={store.openIssues}
          detail={(item) => item.description}
          onOpenSource={onOpenSource}
        />
        <Column
          title="다음 할 일"
          items={store.nextActions}
          detail={(item) =>
            [item.assignee, item.dueAt ? `${formatDate(item.dueAt)}까지` : null]
              .filter(Boolean)
              .join(" · ") || item.description
          }
          onOpenSource={onOpenSource}
        />
      </div>
    </section>
  );
}

/**
 * 현재 상황 카드가 도착하기 전에 자리를 잡아 둡니다.
 *
 * 자리를 비워 두면 카드가 늦게 도착하면서 필터와 목록을 아래로 밀어냅니다.
 */
export function CurrentStateCardSkeleton({ className }: { className?: string }) {
  return (
    <div role="status" className={cn("rounded-xl border border-border bg-card p-4", className)}>
      <span className="sr-only">현재 상황을 불러오는 중</span>
      <div aria-hidden>
        <Skeleton className="h-4 w-20" />
        <Skeleton className="mt-3 h-4 w-full" />
        <Skeleton className="mt-2 h-4 w-2/3" />
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          {[0, 1, 2].map((column) => (
            <div key={column} className="space-y-2">
              <Skeleton className="h-3 w-16" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-4/5" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
