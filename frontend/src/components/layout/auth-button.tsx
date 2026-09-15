"use client";

import { useRouter } from "next/navigation";

import { isSupabaseConfigured } from "@/lib/supabase/config";
import { createClient } from "@/lib/supabase/client";

export function AuthButton() {
  const router = useRouter();
  if (!isSupabaseConfigured) return null;

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
