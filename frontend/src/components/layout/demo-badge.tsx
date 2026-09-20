"use client";

import { useEffect, useId, useRef, useState } from "react";
import { FlaskConical } from "lucide-react";
import { usePathname } from "next/navigation";

import { isMockMode } from "@/lib/api";
import { isDemoPath } from "@/lib/demo-routing";

/**
 * 화면의 내용이 실제 내 데이터가 아님을 알리는 배지입니다.
 *
 * 발표 자리에서 화면의 내용이 실제 데이터로 오해되지 않도록 항상 보이게 두되,
 * 화면 전체를 가로지르는 띠 대신 헤더 안에 작게 둬서 제품 화면을 가리지 않습니다.
 *
 * 두 경우의 사실이 다르므로 문구도 나눕니다.
 * - 데모 경로(`/demo/*`): 공개 데모 워크스페이스를 읽기만 합니다. 실 API에서는 서버의
 *   데모 데이터를 읽어 오므로 "서버에 저장되지 않는다"는 설명은 맞지 않습니다.
 * - 그 밖의 화면에서 mock 모드: 브라우저 메모리의 샘플 데이터라 편집은 되지만
 *   새로 고치면 사라집니다.
 *
 * 설명은 `title` 툴팁이 아니라 눌러서 펼치는 패널에 둡니다. 툴팁은 터치와 키보드로
 * 닿을 수 없습니다. 스크린리더에는 `aria-describedby`로 항상 읽힙니다.
 */
export function DemoBadge() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const isDemo = isDemoPath(pathname);
  if (!isMockMode && !isDemo) return null;

  const label = isDemo ? "읽기 전용 데모" : "샘플 데이터";
  const description = isDemo
    ? "공개 데모 워크스페이스를 살펴보는 화면입니다. 내용을 바꾸거나 새로 올릴 수 없습니다."
    : "브라우저 안의 샘플 데이터로 동작합니다. 바꾼 내용은 서버에 저장되지 않고, 새로 고치면 처음 상태로 돌아갑니다.";

  return (
    <span ref={rootRef} className="relative inline-flex">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-describedby={panelId}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-1 rounded-md bg-accent px-2 py-0.5 text-xs text-accent-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <FlaskConical className="size-3 shrink-0" aria-hidden />
        {label}
      </button>
      <span
        id={panelId}
        role="note"
        hidden={!open}
        className="absolute top-full left-0 z-40 mt-2 w-64 rounded-lg border border-border bg-popover p-3 text-xs leading-relaxed text-popover-foreground shadow-md"
      >
        {description}
      </span>
    </span>
  );
}
