// Enable only after the Kakao app can return a verified account_email.
// Supabase rejects email-less Kakao OAuth while its email requirement is enabled.
export const isKakaoOAuthAvailable = process.env.NEXT_PUBLIC_KAKAO_OAUTH_ENABLED === "true";
