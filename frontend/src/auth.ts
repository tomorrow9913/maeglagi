import NextAuth from "next-auth";

const issuer = process.env.AUTH_ZITADEL_ISSUER ?? "http://localhost:8081";

async function refreshAccessToken(token: Record<string, unknown>) {
  try {
    const response = await fetch(`${issuer}/oauth/v2/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        client_id: process.env.AUTH_ZITADEL_ID ?? "",
        client_secret: process.env.AUTH_ZITADEL_SECRET ?? "",
        grant_type: "refresh_token",
        refresh_token: String(token.refreshToken),
      }),
    });
    const refreshed = (await response.json()) as {
      access_token: string;
      expires_in: number;
      refresh_token?: string;
    };
    if (!response.ok) throw refreshed;
    return {
      ...token,
      accessToken: refreshed.access_token,
      accessTokenExpires: Date.now() + refreshed.expires_in * 1000,
      refreshToken: refreshed.refresh_token ?? token.refreshToken,
      error: undefined,
    };
  } catch {
    return { ...token, error: "RefreshAccessTokenError" };
  }
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  providers: [
    {
      id: "zitadel",
      name: "ZITADEL",
      type: "oidc",
      issuer,
      clientId: process.env.AUTH_ZITADEL_ID,
      clientSecret: process.env.AUTH_ZITADEL_SECRET,
      authorization: { params: { scope: "openid profile email offline_access" } },
    },
  ],
  callbacks: {
    async jwt({ token, account }) {
      if (account) {
        return {
          ...token,
          accessToken: account.access_token,
          accessTokenExpires: (account.expires_at ?? 0) * 1000,
          refreshToken: account.refresh_token,
        };
      }
      if (Date.now() < Number(token.accessTokenExpires ?? 0) - 30_000) return token;
      if (!token.refreshToken) return { ...token, error: "RefreshAccessTokenError" };
      return refreshAccessToken(token);
    },
    async session({ session, token }) {
      session.accessToken = token.accessToken as string | undefined;
      session.error = token.error as string | undefined;
      return session;
    },
  },
});
