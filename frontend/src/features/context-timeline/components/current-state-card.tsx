import type { ContextStore, ContextStoreItem } from "@/lib/api";
import { cn } from "@/lib/utils";

function formatDate(iso: string): string {
  return iso.slice(0, 10);
}

function Column({
  title,
  items,
  detail,
}: {
  title: string;
  items: ContextStoreItem[];
  /** 항목 아래에 덧붙일 한 줄 (담당자·기한·결정일). 없으면 설명을 씁니다. */
  detail: (item: ContextStoreItem) => string;
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
          {items.map((item) => (
            <li key={item.title} className="text-sm">
              <span className="font-medium">{item.title}</span>
              {detail(item) ? (
                <span className="mt-0.5 block text-xs text-muted-foreground">{detail(item)}</span>
              ) : null}
            </li>
          ))}
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
  className,
}: {
  store: ContextStore;
  className?: string;
}) {
  return (
    <section
      aria-label="현재 상황"
      className={cn("rounded-xl border border-border bg-card p-4", className)}
    >
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium">현재 상황</h2>
        <span className="text-xs text-muted-foreground">
          소스 {store.sourceIds.length}개 반영 · {formatDate(store.updatedAt)} 갱신
        </span>
      </div>

      {store.currentState ? (
        <p className="mt-2 text-sm leading-relaxed whitespace-pre-line">{store.currentState}</p>
      ) : null}

      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        <Column
          title="유효한 결정"
          items={store.decisions}
          detail={(item) => (item.decidedAt ? `${item.decidedAt} 결정` : item.description)}
        />
        <Column title="열린 이슈" items={store.openIssues} detail={(item) => item.description} />
        <Column
          title="다음 할 일"
          items={store.nextActions}
          detail={(item) =>
            [item.assignee, item.dueAt ? `${item.dueAt}까지` : null].filter(Boolean).join(" · ") ||
            item.description
          }
        />
      </div>
    </section>
  );
}
