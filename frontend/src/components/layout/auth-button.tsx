"use client";

import { useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";

import { isMockMode, isSupabaseConfigured } from "@/lib/supabase/config";
import { createClient } from "@/lib/supabase/client";
import { isDemoPath } from "@/lib/demo-routing";

export function AuthButton() {
  const router = useRouter();
  const pathname = usePathname();
  const [pending, setPending] = useState(false);
  if (isMockMode || !isSupabaseConfigured || isDemoPath(pathname)) return null;

  return (
    <Button
      variant="ghost"
      size="sm"
      className="ml-auto text-muted-foreground"
      pending={pending}
      pendingLabel="로그아웃하는 중…"
      onClick={async () => {
        setPending(true);
        try {
          const { error } = await createClient().auth.signOut();
          if (error) throw error;
          router.replace("/login");
          router.refresh();
        } catch {
          toast.error("로그아웃하지 못했습니다. 잠시 후 다시 시도해 주세요.");
          setPending(false);
        }
      }}
    >
      로그아웃
    </Button>
  );
}
