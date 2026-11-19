/** Client-side API helper: every call goes through a Studio BFF (/api/nx/...), never to the gateway.
 * In split-origin mode (DV-08), calls for data-plane services go to the data-plane Studio. */

import { dataOrigin, routeFor } from "./split";

export interface Problem {
  title?: string;
  status?: number;
  code?: string;
  detail?: string;
  errors?: { path?: string; loc?: (string | number)[]; message?: string; msg?: string }[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public problem: Problem,
  ) {
    super(problem.detail || problem.title || `Request failed (${status})`);
  }
}

export async function api<T>(
  path: string,
  init: Omit<RequestInit, "body"> & { json?: unknown; body?: BodyInit } = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("x-nexiqon-csrf", "1");
  headers.set("accept", "application/json");
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("content-type", "application/json");
    body = JSON.stringify(init.json);
  }
  const route = routeFor(path, dataOrigin());
  const response = await fetch(route.url, {
    ...init,
    headers,
    body,
    credentials: route.crossOrigin ? "include" : "same-origin",
  });
  if (response.status === 401 && typeof window !== "undefined") {
    const problem = (await response.json().catch(() => ({}))) as Problem;
    if (problem.code === "signed_out" && route.crossOrigin) {
      // Sign in at the data-plane Studio too (same identity provider), then come back here.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- another origin
      window.location.assign(`${new URL(route.url).origin}/auth/login?returnTo=${encodeURIComponent(window.location.href)}`);
    } else if (problem.code === "signed_out") {
      // Full navigation on purpose: sign-in starts in a route handler that redirects to the IdP.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign(`/auth/login?returnTo=${encodeURIComponent(window.location.pathname)}`);
    }
    throw new ApiError(401, problem);
  }
  if (!response.ok) {
    throw new ApiError(response.status, (await response.json().catch(() => ({}))) as Problem);
  }
  if (response.status === 204) return undefined as T;
  const type = response.headers.get("content-type") ?? "";
  return (type.includes("json") ? await response.json() : await response.text()) as T;
}

export async function postJson<T>(url: string, json: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json", "x-nexiqon-csrf": "1" },
    body: JSON.stringify(json),
    credentials: "same-origin",
  });
  if (!response.ok) throw new ApiError(response.status, await response.json().catch(() => ({})));
  return (await response.json()) as T;
}
