import { redirect } from "next/navigation";

import { DEMO_WORKSPACE_ID } from "@/lib/api";
import { workspacePath } from "@/lib/navigation";

export const metadata = {
  title: "데모 | 맥락이",
};

/**
 * 시드 데이터가 들어 있는 워크스페이스로 바로 들어가는 경로입니다.
 *
 * 발표 중에 목록을 거치지 않고 한 번에 화면을 띄우기 위한 것입니다.
 */
export default function DemoEntryPage() {
  redirect(workspacePath(DEMO_WORKSPACE_ID, "timeline"));
}
