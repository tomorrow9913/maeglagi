import { redirect } from "next/navigation";

import { demoPath } from "@/lib/demo-routing";

export const metadata = {
  title: "데모 | 맥락이",
};

/**
 * 인증이 필요 없는 시드 데모의 Ask 화면으로 들어가는 경로입니다.
 *
 * 발표 중에 목록을 거치지 않고 한 번에 화면을 띄우기 위한 것입니다.
 */
export default function DemoEntryPage() {
  redirect(demoPath("ask"));
}
