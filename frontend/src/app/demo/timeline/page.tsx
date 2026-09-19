"use client";

import TimelinePage from "@/app/workspaces/[workspaceId]/timeline/page";
import { useDemoWorkspaceId } from "@/lib/api/context";

export default function DemoTimelinePage() {
  return <TimelinePage params={Promise.resolve({ workspaceId: useDemoWorkspaceId() })} />;
}
