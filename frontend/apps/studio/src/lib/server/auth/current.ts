/** Read (and transparently refresh) the signed-in session on the server. */

import { cookies } from "next/headers";

import { studioEnv } from "../env";
import { cookieOptions, SESSION_COOKIE, seal, type Session, TENANT_COOKIE, unseal } from "../session";
import { refresh } from "./oidc";

const REFRESH_MARGIN_SECONDS = 30;

export async function currentSession(options: { persist?: boolean } = {}): Promise<Session | null> {
  const env = studioEnv();
  const store = await cookies();
  const session = await unseal<Session>(store.get(SESSION_COOKIE)?.value, env.sessionSecret);
  if (!session) return null;
  if (session.expiresAt - REFRESH_MARGIN_SECONDS > Date.now() / 1000) return session;
  const renewed = await refresh(env, session);
  if (renewed && options.persist) {
    // Cookies can only be written from Route Handlers and Server Actions.
    store.set(SESSION_COOKIE, await seal(renewed, env.sessionSecret), cookieOptions(env.secureCookies));
  }
  return renewed;
}

export async function currentTenant(): Promise<string | undefined> {
  return (await cookies()).get(TENANT_COOKIE)?.value || undefined;
}
