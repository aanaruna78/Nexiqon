/**
 * Split-origin Studio for hybrid installs (DV-08). The services that hold customer content run in
 * the customer's data plane; Studio's browser code reaches them through the data-plane Studio
 * (a second backend-for-frontend, at its own origin, with its own session), so their content never
 * passes through the control plane. Everything else goes through this Studio as usual.
 */

/** Services whose responses carry customer content (documents, questions, answers, tool data). */
export const DATA_PLANE_SERVICES = new Set(["ingestion", "retrieval", "agent-runtime", "conversation", "channel", "tool-gateway"]);

export interface Route {
  url: string;
  crossOrigin: boolean;
}

/** Where a BFF call (``service/v1/...``) goes, given the data-plane Studio's origin (or none). */
export function routeFor(path: string, dataOrigin: string | null): Route {
  const clean = path.replace(/^\//, "");
  const service = clean.split("/", 1)[0];
  if (dataOrigin && DATA_PLANE_SERVICES.has(service)) {
    return { url: `${dataOrigin}/api/nx/${clean}`, crossOrigin: true };
  }
  return { url: `/api/nx/${clean}`, crossOrigin: false };
}

export const DATA_ORIGIN_META = "nexiqon-data-origin";

export function dataOrigin(): string | null {
  if (typeof document === "undefined") return null;
  return document.querySelector<HTMLMetaElement>(`meta[name="${DATA_ORIGIN_META}"]`)?.content || null;
}
