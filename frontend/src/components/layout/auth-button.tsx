"use client";

import { usePathname, useRouter } from "next/navigation";

import { isMockMode, isSupabaseConfigured } from "@/lib/supabase/config";
import { createClient } from "@/lib/supabase/client";
import { isDemoPath } from "@/lib/demo-routing";

export function AuthButton() {
  const router = useRouter();
  const pathname = usePathname();
  if (isMockMode || !isSupabaseConfigured || isDemoPath(pathname)) return null;

  return (
    <button
      className="ml-auto text-sm text-muted-foreground hover:text-foreground"
      onClick={async () => {
        await createClient().auth.signOut();
        router.replace("/login");
        router.refresh();
      }}
    >
      로그아웃
    </button>
  );
}
