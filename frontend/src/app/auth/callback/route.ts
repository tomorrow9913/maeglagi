import { NextResponse } from "next/server";

import { createClient } from "@/lib/supabase/server";
import { safeNextPath } from "@/lib/auth-redirect";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const next = safeNextPath(url.searchParams.get("next"));
  const isIdentityLink = url.searchParams.get("intent") === "link";
  if (code) {
    const supabase = await createClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) return NextResponse.redirect(new URL(next, url.origin));
  }
  if (isIdentityLink && next.startsWith("/account/")) {
    const account = new URL(next, url.origin);
    account.searchParams.set("error", "identity_link");
    return NextResponse.redirect(account);
  }
  const login = new URL("/login", url.origin);
  login.searchParams.set("error", "callback");
  if (next !== "/workspaces") login.searchParams.set("next", next);
  return NextResponse.redirect(login);
}
