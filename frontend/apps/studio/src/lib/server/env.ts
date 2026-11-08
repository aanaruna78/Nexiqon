/**
 * Studio server configuration (BFF). Read on the server only; never imported by client components.
 *
 *   NEXIQON_GATEWAY_URL     gateway base URL              (default http://localhost:8000)
 *   STUDIO_BASE_URL         public URL of Studio           (default http://localhost:3100)
 *   STUDIO_AUTH_PROVIDER    oidc | clerk                   (default oidc; Keycloak, Auth0, any OIDC)
 *   OIDC_ISSUER / OIDC_CLIENT_ID / OIDC_CLIENT_SECRET (optional for public PKCE clients)
 *   STUDIO_SESSION_SECRET   >= 32 characters, encrypts the session cookie
 *   STUDIO_ENVIRONMENT      development | staging | production (badge in the sidebar)
 */

const DEV_SECRET = "dev-only-session-secret-change-me-please-0123";

export interface StudioEnv {
  environment: "development" | "staging" | "production";
  gatewayUrl: string;
  baseUrl: string;
  authProvider: "oidc" | "clerk";
  oidcIssuer: string;
  oidcClientId: string;
  oidcClientSecret?: string;
  sessionSecret: string;
  secureCookies: boolean;
}

export function studioEnv(): StudioEnv {
  const production = process.env.NODE_ENV === "production" && process.env.STUDIO_INSECURE_DEV !== "1";
  const sessionSecret = process.env.STUDIO_SESSION_SECRET ?? (production ? "" : DEV_SECRET);
  if (sessionSecret.length < 32) {
    throw new Error("STUDIO_SESSION_SECRET must be at least 32 characters");
  }
  const baseUrl = (process.env.STUDIO_BASE_URL ?? "http://localhost:3100").replace(/\/$/, "");
  const environment = process.env.STUDIO_ENVIRONMENT;
  return {
    environment: environment === "staging" || environment === "production" ? environment : "development",
    gatewayUrl: (process.env.NEXIQON_GATEWAY_URL ?? "http://localhost:8000").replace(/\/$/, ""),
    baseUrl,
    authProvider: process.env.STUDIO_AUTH_PROVIDER === "clerk" ? "clerk" : "oidc",
    oidcIssuer: process.env.OIDC_ISSUER ?? "http://localhost:8080/realms/nexiqon",
    oidcClientId: process.env.OIDC_CLIENT_ID ?? "nexiqon-studio",
    oidcClientSecret: process.env.OIDC_CLIENT_SECRET || undefined,
    sessionSecret,
    secureCookies: baseUrl.startsWith("https://"),
  };
}
