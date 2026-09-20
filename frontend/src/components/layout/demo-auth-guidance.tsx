"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { useApi } from "@/lib/api/context";
import { workspacePath } from "@/lib/navigation";
import { createClient } from "@/lib/supabase/client";
import { isSupabaseConfigured } from "@/lib/supabase/config";
import { watchDemoAuthState, type DemoAuthState } from "@/lib/demo-auth-state";
import { toUserMessage } from "@/lib/api/error-message";

export function DemoAuthGuidance() {
  const router = useRouter();
  const api = useApi();
  const copyPending = useRef(false);
  const [authState, setAuthState] = useState<DemoAuthState>("loading");
  const [copying, setCopying] = useState(false);
  const [copyError, setCopyError] = useState<string>();

  useEffect(() => {
    if (!isSupabaseConfigured) {
      setAuthState("signed-out");
      return;
    }
    return watchDemoAuthState(createClient().auth, setAuthState);
  }, []);

  async function copyDemo() {
    if (copyPending.current || authState !== "signed-in") return;
    copyPending.current = true;
    setCopying(true);
    setCopyError(undefined);
    try {
      const workspace = await api.cloneDemoWorkspace();
      router.push(workspacePath(workspace.id, "ask"));
    } catch (error) {
      setCopyError(toUserMessage(error, "데모를 복사하지 못했습니다."));
      setCopying(false);
      copyPending.current = false;
    }
  }

  return (
    <div className="space-y-2">
      <p className="text-sm text-muted-foreground">
        공개 데모는 읽기 전용입니다. 복사본은 내 워크스페이스에서 편집할 수 있습니다.
      </p>
      <p className="text-sm text-muted-foreground">
        결정·이벤트 이력과 편집 체험용 회의록 초안을 함께 복사합니다. 복사 후 소스에서
        ‘편집 체험용 초안’을 열어 발언과 화자를 수정해 보세요.
        복사와 편집에는 API 키가 필요 없으며, AI 질문·분석에는 본인의 프로바이더 연결이 필요합니다.
      </p>
      {authState === "loading" ? (
        <p className="text-sm text-muted-foreground" role="status">로그인 상태를 확인하는 중입니다.</p>
      ) : authState === "signed-in" ? (
        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" disabled={copying} onClick={() => void copyDemo()}>
            {copying ? "복사하는 중…" : "내 워크스페이스로 복사해서 체험"}
          </Button>
          <Link href="/workspaces" className="text-sm text-muted-foreground underline">내 워크스페이스</Link>
        </div>
      ) : (
        <Button asChild><Link href="/login?next=/demo/ask">로그인하고 복사해서 체험</Link></Button>
      )}
      {copyError && <p role="alert" className="text-sm text-destructive">{copyError}</p>}
    </div>
  );
}
