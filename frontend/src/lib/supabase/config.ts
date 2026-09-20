export const isSupabaseConfigured = Boolean(
  process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
);

/**
 * mock 여부는 API 계층과 같은 기준을 씁니다. 기준이 어긋나면 실제 API를 부르면서
 * 인증 가드만 꺼지는 상태가 생깁니다.
 */
export { USE_MOCKS as isMockMode } from "../api/config";

export function supabaseConfig(): { url: string; key: string } {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !key) throw new Error("Supabase environment variables are not configured");
  return { url, key };
}
