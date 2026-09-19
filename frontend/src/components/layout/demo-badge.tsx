"use client";

import { FlaskConical } from "lucide-react";
import { usePathname } from "next/navigation";

import { isMockMode } from "@/lib/api";
import { isDemoPath } from "@/lib/demo-routing";

/**
 * mock 데이터로 동작 중임을 알리는 배지입니다.
 *
 * 발표 자리에서 화면의 내용이 실제 데이터로 오해되지 않도록 항상 보이게 두되,
 * 화면 전체를 가로지르는 띠 대신 헤더 안에 작게 둬서 제품 화면을 가리지 않습니다.
 * 데모 경로에서는 실 API 모드에서도 보이며, 일반 화면에서는 mock 모드에만 보입니다.
 */
export function DemoBadge() {
  const pathname = usePathname();
  if (!isMockMode && !isDemoPath(pathname)) return null;

  return (
    <span
      title="화면의 내용은 시드 데이터이며 서버에 저장되지 않습니다."
      className="inline-flex items-center gap-1 rounded-md bg-accent px-2 py-0.5 text-xs text-accent-foreground"
    >
      <FlaskConical className="size-3 shrink-0" aria-hidden />
      시드 데이터
    </span>
  );
}
