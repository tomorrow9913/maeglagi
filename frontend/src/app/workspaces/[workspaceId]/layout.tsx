import type { ReactNode } from "react";

import { WorkspaceNav } from "@/components/layout/workspace-nav";

export default async function WorkspaceLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 gap-8 px-5 py-8">
      <aside className="hidden w-48 shrink-0 md:block">
        <WorkspaceNav workspaceId={workspaceId} />
      </aside>
      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}
