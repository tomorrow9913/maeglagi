"use client";

import GraphPage from "@/app/workspaces/[workspaceId]/graph/page";
import { useDemoWorkspaceId } from "@/lib/api/context";

export default function DemoGraphPage() {
  return <GraphPage params={Promise.resolve({ workspaceId: useDemoWorkspaceId() })} />;
}
