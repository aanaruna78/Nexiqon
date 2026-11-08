/** Encrypted, httpOnly session cookie (JWE dir/A256GCM). Tokens never reach browser JavaScript. */

import { EncryptJWT, jwtDecrypt } from "jose";

export const SESSION_COOKIE = "nx_session";
export const FLOW_COOKIE = "nx_auth";
export const TENANT_COOKIE = "nx_tenant";
/** ID token kept apart (encrypted) only as the logout hint, so the session cookie stays small. */
export const ID_TOKEN_COOKIE = "nx_idt";
export const SESSION_MAX_AGE = 8 * 3600;

export interface SessionUser {
  sub: string;
  name?: string;
  email?: string;
}

export interface Session {
  accessToken: string;
  refreshToken?: string;
  expiresAt: number; // epoch seconds of the access token
  user: SessionUser;
}

async function key(secret: string): Promise<Uint8Array> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(secret));
  return new Uint8Array(digest);
}

export async function seal(payload: object, secret: string, maxAgeSeconds = SESSION_MAX_AGE): Promise<string> {
  return new EncryptJWT({ ...payload })
    .setProtectedHeader({ alg: "dir", enc: "A256GCM" })
    .setIssuedAt()
    .setExpirationTime(`${maxAgeSeconds}s`)
    .encrypt(await key(secret));
}

export async function unseal<T>(token: string | undefined, secret: string): Promise<T | null> {
  if (!token) return null;
  try {
    const { payload } = await jwtDecrypt(token, await key(secret));
    return payload as unknown as T;
  } catch {
    return null; // tampered, expired, or encrypted with another secret
  }
}

export function cookieOptions(secure: boolean, maxAge = SESSION_MAX_AGE) {
  return { httpOnly: true, secure, sameSite: "lax" as const, path: "/", maxAge };
}

/** Only same-site relative paths are valid post-login destinations (no open redirects). */
export function safeReturnTo(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return "/";
  return value;
}
