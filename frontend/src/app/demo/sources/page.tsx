import SourcesPage from "@/app/workspaces/[workspaceId]/sources/page";
import { DEMO_WORKSPACE_ID } from "@/lib/api";

export default function DemoSourcesPage() {
  return <SourcesPage params={Promise.resolve({ workspaceId: DEMO_WORKSPACE_ID })} />;
}
