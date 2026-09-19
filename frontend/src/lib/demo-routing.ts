/** Keep the public demo boundary separate from real workspace URLs. */
export function demoPath(segment?: string): string {
  return segment ? `/demo/${segment}` : "/demo";
}

export function isDemoPath(pathname: string): boolean {
  return pathname === "/demo" || pathname.startsWith("/demo/");
}

export function requiresWorkspaceAuth(pathname: string): boolean {
  return pathname === "/workspaces" || pathname.startsWith("/workspaces/") || pathname === "/account" || pathname.startsWith("/account/");
}

export function selectRouteApi<T>(isDemo: boolean, workspaceApi: T, seededApi: T): T {
  return isDemo ? seededApi : workspaceApi;
}
