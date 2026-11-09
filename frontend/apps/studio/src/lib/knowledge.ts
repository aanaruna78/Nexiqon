/** Knowledge types (mirroring contracts/openapi/{ingestion,retrieval}.json) and pure helpers. */

import type { Tone } from "@/components/visual/icon-tile";

export type Classification = "public" | "internal" | "confidential" | "restricted";
export const CLASSIFICATIONS: Classification[] = ["public", "internal", "confidential", "restricted"];

export interface Collection {
  id: string;
  name: string;
  description: string;
  model_profile: string;
  retrieval_profile: string;
  classification: Classification;
  acl_groups: string[];
  embedding_model: string | null;
  documents: number;
  created_at: string;
}

export type DocumentStatus = "pending" | "processing" | "ready" | "failed" | "quarantined" | "deleted";

export interface KnowledgeDocument {
  id: string;
  collection_id: string;
  source_id: string;
  uri: string;
  title: string | null;
  media_type: string | null;
  size: number;
  version: number;
  indexed_version: number | null;
  status: DocumentStatus;
  error_code: string | null;
  error_detail: string | null;
  scanner: string | null;
  section_count: number;
  chunk_count: number;
  token_count: number;
  updated_at: string;
  indexed_at: string | null;
}

export interface Source {
  id: string;
  collection_id: string;
  name: string;
  connector: string;
  config: Record<string, unknown>;
  schedule_hours: number | null;
  status: "idle" | "syncing";
  last_run_id: string | null;
  last_synced_at: string | null;
}

export interface Run {
  id: string;
  collection_id: string;
  source_id: string | null;
  kind: "sync" | "upload" | "reindex";
  status: "queued" | "running" | "completed" | "failed";
  workflow_id: string | null;
  discovered: number;
  processed: number;
  unchanged: number;
  failed: number;
  quarantined: number;
  deleted: number;
  truncated: boolean;
  incomplete: boolean;
  warnings: { uri: string; message: string }[];
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface PluginManifest {
  name: string;
  kind: "connector" | "parser" | "chunker";
  title: string;
  description: string;
  config_schema: Record<string, unknown>;
  capabilities: string[];
  media_types: string[];
  extensions: string[];
  icon: string | null;
}

export interface OutlineNode {
  id: string;
  parent_id: string | null;
  path: string;
  kind: "document" | "section" | "chunk" | "summary";
  title: string | null;
  heading_path: string[];
  page_start: number | null;
  page_end: number | null;
  token_count: number;
}

export interface Passage {
  id: string;
  kind: "section" | "chunk";
  document_id: string;
  collection_id: string;
  title: string | null;
  heading_path: string[];
  citation: string;
  page_start: number | null;
  page_end: number | null;
  source_uri: string | null;
  text: string;
  token_count: number;
  score: number;
  chunk_ids: string[];
  classification: Classification;
  truncated: boolean;
}

export interface SearchResponse {
  passages: Passage[];
  abstain: boolean;
  evidence_score: number;
  embedding_model: string | null;
  reranked: boolean;
  timings_ms: Record<string, number>;
}

export interface AnswerResponse {
  answer: string | null;
  abstained: boolean;
  reason: string | null;
  citations: { marker: string; passage_id: string; citation: string }[];
  removed: { marker: string; reason: string }[];
  search: SearchResponse;
  model: Record<string, unknown>;
  usage: Record<string, number>;
}

export interface ProfileOption {
  name: string;
  source: string | null;
  allowed: boolean;
  reason: string | null;
  profile: Record<string, unknown> | null;
}

// ------------------------------------------------------------------ status and progress

export function documentTone(status: DocumentStatus): Tone {
  return ({ ready: "teal", pending: "sky", processing: "sky", failed: "rose", quarantined: "amber", deleted: "slate" } as const)[status];
}

export function isBusy(status: DocumentStatus): boolean {
  return status === "pending" || status === "processing";
}

export function runIsActive(run: Pick<Run, "status">): boolean {
  return run.status === "queued" || run.status === "running";
}

/** Items handled so far out of those discovered (0..1). */
export function runProgress(run: Run): { done: number; total: number; ratio: number } {
  const done = run.processed + run.unchanged + run.failed + run.quarantined;
  const total = Math.max(run.discovered, done);
  return { done, total, ratio: total ? done / total : run.status === "completed" ? 1 : 0 };
}

/** Error codes with a written fix hint (messages: knowledge.errorHints.<code>). */
export const KNOWN_ERRORS = [
  "unsupported_type",
  "parse_failed",
  "empty_document",
  "malware_detected",
  "scan_unavailable",
  "fetch_blocked",
  "fetch_failed",
  "too_large",
  "credentials_missing",
  "embedding_failed",
  "embedding_model_changed",
  "profile_unavailable",
  "temporarily_unavailable",
] as const;

export function errorHintKey(code: string | null): string {
  return code && (KNOWN_ERRORS as readonly string[]).includes(code) ? code : "unknown";
}

// ------------------------------------------------------------------ files

export interface UploadRules {
  accept: string; // for <input accept>
  extensions: string[];
  maxBytes: number;
}

export function uploadRules(parsers: PluginManifest[], maxBytes = 50 * 1024 * 1024): UploadRules {
  const extensions = [...new Set(parsers.flatMap((p) => p.extensions.map((e) => e.toLowerCase())))].sort();
  const media = [...new Set(parsers.flatMap((p) => p.media_types))].sort();
  return { accept: [...extensions, ...media].join(","), extensions, maxBytes };
}

export type FileProblem = "too_large" | "unsupported_type" | "empty";

export function checkFile(file: { name: string; size: number }, rules: UploadRules): FileProblem | null {
  if (file.size === 0) return "empty";
  if (file.size > rules.maxBytes) return "too_large";
  const name = file.name.toLowerCase();
  if (rules.extensions.length && !rules.extensions.some((ext) => name.endsWith(ext))) return "unsupported_type";
  return null;
}

export function formatBytes(bytes: number, locale = "en"): string {
  const units = ["byte", "kilobyte", "megabyte", "gigabyte"] as const;
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return new Intl.NumberFormat(locale, { style: "unit", unit: units[i], unitDisplay: "short", maximumFractionDigits: i ? 1 : 0 }).format(value);
}

/** A friendly label for a document: its title, else the last segment of its URI. */
export function documentLabel(doc: Pick<KnowledgeDocument, "title" | "uri">): string {
  if (doc.title) return doc.title;
  const tail = doc.uri.replace(/^upload:\/\//, "").replace(/[#?].*$/, "").split("/").filter(Boolean).pop();
  return tail || doc.uri;
}

// ------------------------------------------------------------------ search display

/** Split text into plain and highlighted segments for the query's words (case-insensitive). */
export function highlight(text: string, query: string): { text: string; match: boolean }[] {
  const words = [...new Set(query.toLowerCase().match(/[\p{L}\p{N}]{3,}/gu) ?? [])];
  if (!words.length) return [{ text, match: false }];
  const pattern = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "giu");
  return text
    .split(pattern)
    .filter((part) => part !== "")
    .map((part) => ({ text: part, match: words.includes(part.toLowerCase()) }));
}

/** Split an answer into text and [n] citation markers. */
export function answerParts(answer: string): ({ text: string } | { marker: string })[] {
  return answer
    .split(/(\[\w{1,8}\])/)
    .filter(Boolean)
    .map((part) => {
      const m = /^\[(\w{1,8})\]$/.exec(part);
      return m ? { marker: m[1] } : { text: part };
    });
}

export function isWebUri(uri: string | null): uri is string {
  return !!uri && /^https?:\/\//.test(uri);
}
