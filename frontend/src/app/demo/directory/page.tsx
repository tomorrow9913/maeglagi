import DirectoryPage from "@/app/workspaces/[workspaceId]/directory/page";
import { DEMO_WORKSPACE_ID } from "@/lib/api";

export default function DemoDirectoryPage() {
  return <DirectoryPage params={Promise.resolve({ workspaceId: DEMO_WORKSPACE_ID })} />;
}
