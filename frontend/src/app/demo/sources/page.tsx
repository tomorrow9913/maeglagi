"use client";

import SourcesPage from "@/app/workspaces/[workspaceId]/sources/page";
import { useDemoWorkspaceId } from "@/lib/api/context";

export default function DemoSourcesPage() {
  return <SourcesPage params={Promise.resolve({ workspaceId: useDemoWorkspaceId() })} />;
}
