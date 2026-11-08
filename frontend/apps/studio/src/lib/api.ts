/** Client-side API helper: every call goes through Studio's BFF (/api/nx/...), never to the gateway. */

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
  const response = await fetch(`/api/nx/${path.replace(/^\//, "")}`, {
    ...init,
    headers,
    body,
    credentials: "same-origin",
  });
  if (response.status === 401 && typeof window !== "undefined") {
    const problem = (await response.json().catch(() => ({}))) as Problem;
    if (problem.code === "signed_out") {
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
