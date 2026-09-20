"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { useSelectedLayoutSegment } from "next/navigation";

import { useWorkspacePath } from "@/lib/api/context";
import { cn } from "@/lib/utils";
import { workspaceNavItems } from "@/lib/navigation";

export function WorkspaceNav({ workspaceId }: { workspaceId: string }) {
  const segment = useSelectedLayoutSegment();
  const workspacePath = useWorkspacePath();
  const navRef = useRef<HTMLElement>(null);

  /*
   * 모바일에서는 한 줄 가로 스크롤입니다. 뒤쪽 메뉴(Graph, 설정)로 들어왔을 때 현재
   * 항목이 화면 밖에 있지 않도록 가운데로 옮깁니다. `scrollIntoView`는 페이지까지
   * 세로로 움직일 수 있어 nav의 가로 위치만 직접 계산합니다.
   */
  useEffect(() => {
    const nav = navRef.current;
    if (!nav || nav.scrollWidth <= nav.clientWidth) return;
    const active = nav.querySelector<HTMLElement>('[aria-current="page"]');
    if (!active) return;

    const navBox = nav.getBoundingClientRect();
    const activeBox = active.getBoundingClientRect();
    const offset = activeBox.left - navBox.left - (navBox.width - activeBox.width) / 2;
    nav.scrollLeft += offset;
  }, [segment]);

  return (
    <nav
      ref={navRef}
      aria-label="워크스페이스 메뉴"
      className={cn(
        // 모바일: 줄바꿈 없이 한 줄. 스크롤바는 숨겨 높이가 들썩이지 않게 합니다.
        "-mx-5 flex [scrollbar-width:none] flex-nowrap gap-1 overflow-x-auto px-5 py-1 [&::-webkit-scrollbar]:hidden",
        // md 이상: 세로 목록
        "md:mx-0 md:flex-col md:overflow-visible md:p-0",
      )}
    >
      {workspaceNavItems.map((item) => {
        const Icon = item.icon;
        const isActive = segment === item.segment;

        return (
          <Link
            key={item.segment}
            href={workspacePath(workspaceId, item.segment)}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "flex shrink-0 items-center gap-2.5 rounded-md px-3 py-2 text-sm whitespace-nowrap transition-colors",
              isActive
                ? "bg-accent font-medium text-accent-foreground"
                : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
            )}
          >
            <Icon className="size-4 shrink-0" aria-hidden />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
