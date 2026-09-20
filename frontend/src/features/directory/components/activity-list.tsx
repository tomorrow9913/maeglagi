"use client";

import Link from "next/link";

import type { PersonActivity } from "@/features/directory/lib/person-context";
import { useWorkspacePath } from "@/lib/api/context";

/** 참여자 상세의 업무·결정·이벤트 목록. 항목마다 근거 소스로 가는 링크를 붙입니다. */
export function ActivityList({
  items,
  empty,
  workspaceId,
}: {
  items: PersonActivity[];
  empty: string;
  workspaceId: string;
}) {
  const workspacePath = useWorkspacePath();
  if (!items.length) return <p className="text-muted-foreground">{empty}</p>;
  return (
    <ul className="space-y-2">
      {items.map((item) => (
        <li key={item.node.id} className="rounded-md border p-2">
          <p className="font-medium">{item.node.label}</p>
          {item.node.type === "decision" && item.node.supersededBy && (
            <p className="text-xs text-muted-foreground">대체된 결정</p>
          )}
          <p className="text-xs text-muted-foreground">
            {item.relation}
            {item.via ? ` · ${item.via.label} 경유` : ""}
          </p>
          {item.node.sources.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-2">
              {item.node.sources.map((source) => (
                <Link
                  key={source.id}
                  href={`${workspacePath(workspaceId, "sources")}?source=${encodeURIComponent(source.id)}${source.chunkId ? `&chunk=${encodeURIComponent(source.chunkId)}` : ""}`}
                  className="text-xs underline underline-offset-2"
                >
                  {source.title}
                </Link>
              ))}
            </div>
          )}
          {item.decisions?.length ? (
            <div className="mt-2 border-l pl-2">
              <p className="text-xs font-medium">연결된 결정</p>
              {item.decisions.map((decision) => (
                <p key={decision.node.id} className="text-xs">
                  {decision.node.label}
                  {decision.node.supersededBy && (
                    <span className="ml-2 text-muted-foreground">대체된 결정</span>
                  )}
                </p>
              ))}
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
