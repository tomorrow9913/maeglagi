"use client";

import { useEffect, type ReactNode } from "react";

export function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  /*
   * 화면이 모두 클라이언트 컴포넌트라 `metadata`로 제목을 줄 수 없습니다. 탭이 전부
   * "맥락이"로 보이면 여러 탭을 구분할 수 없으므로 여기서 화면 이름을 붙입니다.
   * 떠날 때 되돌리지 않습니다. 다음 화면이 자기 제목을 씁니다.
   */
  useEffect(() => {
    document.title = `${title} | 맥락이`;
  }, [title]);

  return (
    <div className="flex flex-wrap items-start justify-between gap-4 pb-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description ? <p className="text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}
