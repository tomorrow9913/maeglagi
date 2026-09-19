"use client";

import DirectoryPage from "@/app/workspaces/[workspaceId]/directory/page";
import { useDemoWorkspaceId } from "@/lib/api/context";

export default function DemoDirectoryPage() {
  return <DirectoryPage params={Promise.resolve({ workspaceId: useDemoWorkspaceId() })} />;
}
