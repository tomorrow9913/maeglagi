import { createServerClient } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";

import { isMockMode, isSupabaseConfigured, supabaseConfig } from "./config";
import { isDemoPath, requiresWorkspaceAuth } from "@/lib/demo-routing";

export async function updateSession(request: NextRequest) {
  if (isDemoPath(request.nextUrl.pathname) || isMockMode || !isSupabaseConfigured)
    return NextResponse.next({ request });

  let response = NextResponse.next({ request });
  const { url, key } = supabaseConfig();
  const supabase = createServerClient(url, key, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) =>
          response.cookies.set(name, value, options),
        );
      },
    },
  });

  const { data } = await supabase.auth.getUser();
  if (!data.user && requiresWorkspaceAuth(request.nextUrl.pathname)) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    // 근거 링크처럼 쿼리가 붙은 주소도 로그인 뒤 그대로 돌아오게 합니다.
    url.search = "";
    url.searchParams.set("next", `${request.nextUrl.pathname}${request.nextUrl.search}`);
    return NextResponse.redirect(url);
  }
  return response;
}
