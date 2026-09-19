"use client";

import Link from "next/link";
import { useSelectedLayoutSegment } from "next/navigation";

import { cn } from "@/lib/utils";
import { workspaceNavItems, workspacePath } from "@/lib/navigation";

export function WorkspaceNav({ workspaceId }: { workspaceId: string }) {
  const segment = useSelectedLayoutSegment();

  return (
    <nav aria-label="워크스페이스 메뉴" className="flex flex-wrap gap-1 md:flex-col">
      {workspaceNavItems.map((item) => {
        const Icon = item.icon;
        const isActive = segment === item.segment;

        return (
          <Link
            key={item.segment}
            href={workspacePath(workspaceId, item.segment)}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
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
