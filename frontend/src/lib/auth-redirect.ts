const DEFAULT_NEXT = "/workspaces";

/** Accept only same-site path references, including after URL decoding. */
export function safeNextPath(value: string | null): string {
  if (!value) return DEFAULT_NEXT;
  let decoded = value;
  try {
    // Repeated encoding must not turn a path into a network-path reference.
    for (let i = 0; i < 10; i++) {
      const next = decodeURIComponent(decoded);
      if (next === decoded) break;
      decoded = next;
      if (i === 9) return DEFAULT_NEXT;
    }
  } catch {
    return DEFAULT_NEXT;
  }
  if (
    !decoded.startsWith("/") ||
    decoded.startsWith("//") ||
    /[\\\u0000-\u001f\u007f]/.test(decoded)
  )
    return DEFAULT_NEXT;
  return value;
}

export function authCallbackUrl(origin: string, next: string): string {
  const callback = new URL("/auth/callback", origin);
  if (next !== DEFAULT_NEXT) callback.searchParams.set("next", next);
  return callback.toString();
}

/** Override Supabase Kakao's default scope, which includes account_email. */
export function kakaoOAuthOptions(origin: string, next: string) {
  return {
    provider: "kakao" as const,
    options: {
      queryParams: { scope: "profile_nickname profile_image" },
      redirectTo: authCallbackUrl(origin, next),
    },
  };
}
