import { FlaskConical } from "lucide-react";

import { isMockMode } from "@/lib/api";

/**
 * mock 데이터로 동작 중임을 알리는 띠입니다.
 *
 * 발표 자리에서 화면의 수치가 실제 데이터로 오해되지 않도록 항상 보이게
 * 둡니다. 실 API가 붙으면 자동으로 사라집니다.
 */
export function DemoBanner() {
  if (!isMockMode) return null;

  return (
    <div className="flex items-center justify-center gap-2 bg-accent px-4 py-1.5 text-center text-xs text-accent-foreground">
      <FlaskConical className="size-3.5 shrink-0" aria-hidden />
      <span>데모 모드입니다. 화면의 내용은 시드 데이터이며 서버에 저장되지 않습니다.</span>
    </div>
  );
}
