/** OIDC adapter (Keycloak, Auth0, any OpenID provider): authorization code + PKCE, refresh, logout. */

import * as client from "openid-client";

import type { StudioEnv } from "../env";
import type { Session } from "../session";

export interface LoginFlow {
  verifier: string;
  state: string;
  nonce: string;
  returnTo: string;
}

let configuration: Promise<client.Configuration> | null = null;

export function oidcConfig(env: StudioEnv): Promise<client.Configuration> {
  if (!configuration) {
    const issuer = new URL(env.oidcIssuer);
    // Plain-HTTP issuers only for local development (or an explicit opt-in for local e2e runs).
    const insecure =
      issuer.protocol === "http:" &&
      (process.env.NODE_ENV !== "production" || process.env.STUDIO_ALLOW_INSECURE_IDP === "1");
    configuration = client
      .discovery(
        issuer,
        env.oidcClientId,
        env.oidcClientSecret,
        env.oidcClientSecret ? undefined : client.None(),
        insecure ? { execute: [client.allowInsecureRequests] } : undefined,
      )
      .catch((err: unknown) => {
        configuration = null; // retry discovery on the next login
        throw err;
      });
  }
  return configuration;
}

export async function startLogin(env: StudioEnv, returnTo: string): Promise<{ url: URL; flow: LoginFlow }> {
  const config = await oidcConfig(env);
  const flow: LoginFlow = {
    verifier: client.randomPKCECodeVerifier(),
    state: client.randomState(),
    nonce: client.randomNonce(),
    returnTo,
  };
  const url = client.buildAuthorizationUrl(config, {
    redirect_uri: `${env.baseUrl}/auth/callback`,
    scope: "openid email profile",
    code_challenge: await client.calculatePKCECodeChallenge(flow.verifier),
    code_challenge_method: "S256",
    state: flow.state,
    nonce: flow.nonce,
  });
  return { url, flow };
}

function toSession(tokens: client.TokenEndpointResponse & client.TokenEndpointResponseHelpers): Session & { idToken?: string } {
  const claims = tokens.claims();
  return {
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
    expiresAt: Math.floor(Date.now() / 1000) + (tokens.expiresIn() ?? 300),
    idToken: tokens.id_token,
    user: {
      sub: String(claims?.sub ?? ""),
      name: typeof claims?.name === "string" ? claims.name : undefined,
      email: typeof claims?.email === "string" ? claims.email : undefined,
    },
  };
}

export async function finishLogin(
  env: StudioEnv,
  currentUrl: URL,
  flow: LoginFlow,
): Promise<Session & { idToken?: string }> {
  const config = await oidcConfig(env);
  const tokens = await client.authorizationCodeGrant(config, currentUrl, {
    pkceCodeVerifier: flow.verifier,
    expectedState: flow.state,
    expectedNonce: flow.nonce,
    idTokenExpected: true,
  });
  return toSession(tokens);
}

export async function refresh(env: StudioEnv, session: Session): Promise<Session | null> {
  if (!session.refreshToken) return null;
  try {
    const tokens = await client.refreshTokenGrant(await oidcConfig(env), session.refreshToken);
    const next: Session = toSession(tokens);
    delete (next as Session & { idToken?: string }).idToken; // the logout hint is kept elsewhere
    return { ...next, refreshToken: next.refreshToken ?? session.refreshToken, user: session.user };
  } catch {
    return null; // refresh token expired or revoked: sign in again
  }
}

export async function logoutUrl(env: StudioEnv, idToken?: string): Promise<string> {
  try {
    const config = await oidcConfig(env);
    return client
      .buildEndSessionUrl(config, {
        client_id: env.oidcClientId,
        post_logout_redirect_uri: `${env.baseUrl}/signed-out`,
        // With the hint the IdP ends the session without an extra confirmation page.
        ...(idToken ? { id_token_hint: idToken } : {}),
      })
      .toString();
  } catch {
    return `${env.baseUrl}/signed-out`;
  }
}
