import GraphPage from "@/app/workspaces/[workspaceId]/graph/page";
import { DEMO_WORKSPACE_ID } from "@/lib/api";

export default function DemoGraphPage() {
  return <GraphPage params={Promise.resolve({ workspaceId: DEMO_WORKSPACE_ID })} />;
}
