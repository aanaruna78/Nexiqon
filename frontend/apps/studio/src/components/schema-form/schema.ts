/** JSON Schema helpers for the schema-driven form (ST-02). Pure functions, unit-tested. */

import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";

export interface JsonSchema {
  type?: string | string[];
  title?: string;
  description?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  additionalProperties?: boolean | JsonSchema;
  propertyNames?: JsonSchema;
  items?: JsonSchema;
  enum?: unknown[];
  const?: unknown;
  format?: string;
  pattern?: string;
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  minItems?: number;
  maxItems?: number;
  default?: unknown;
  "x-ui"?: { widget?: "textarea" | "color" | string; advanced?: boolean };
  [key: string]: unknown;
}

export type FieldKind =
  | "object"
  | "string-map"
  | "json"
  | "enum"
  | "const"
  | "boolean"
  | "number"
  | "text"
  | "textarea"
  | "color"
  | "string-list"
  | "object-list";

export function typeOf(schema: JsonSchema): string | undefined {
  return Array.isArray(schema.type) ? schema.type.find((t) => t !== "null") : schema.type;
}

export function fieldKind(schema: JsonSchema): FieldKind {
  if (schema.const !== undefined) return "const";
  if (schema.enum) return "enum";
  const type = typeOf(schema);
  if (type === "object") {
    if (schema.properties) return "object";
    const ap = schema.additionalProperties;
    if (ap && typeof ap === "object" && typeOf(ap) === "string" && !ap.enum) return "string-map";
    return "json";
  }
  if (type === "array") {
    const items = schema.items ?? {};
    if (typeOf(items) === "string" && !items.enum) return "string-list";
    if (typeOf(items) === "object" && items.properties) return "object-list";
    return "json";
  }
  if (type === "boolean") return "boolean";
  if (type === "number" || type === "integer") return "number";
  if (type === "string") {
    if (schema["x-ui"]?.widget === "color") return "color";
    if (schema["x-ui"]?.widget === "textarea" || (schema.maxLength ?? 0) > 200) return "textarea";
    return "text";
  }
  return "json";
}

/** "max_answer_tokens" -> "Max answer tokens" */
export function humanize(key: string): string {
  const words = key.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ").trim().toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function labelFor(key: string, schema: JsonSchema): string {
  return schema.title ?? humanize(key);
}

export function isAdvanced(schema: JsonSchema): boolean {
  return schema["x-ui"]?.advanced === true;
}

/** Dotted paths, matching the config service's problem paths ("guardrails.min_evidence_score"). */
export function joinPath(base: string, key: string | number): string {
  return base ? `${base}.${key}` : String(key);
}

export function fieldId(prefix: string, path: string): string {
  return `${prefix}-${path.replace(/[^a-zA-Z0-9_-]/g, "-") || "root"}`;
}

export function getAt(value: unknown, path: string): unknown {
  if (!path) return value;
  let node: unknown = value;
  for (const part of path.split(".")) {
    if (node === null || typeof node !== "object") return undefined;
    node = (node as Record<string, unknown>)[part];
  }
  return node;
}

/** Immutable set; ``undefined`` removes the key so optional fields stay absent from the spec. */
export function setAt<T>(value: T, path: string, next: unknown): T {
  if (!path) return next as T;
  const [head, ...rest] = path.split(".");
  const container: Record<string, unknown> | unknown[] = Array.isArray(value)
    ? [...value]
    : { ...((value as Record<string, unknown>) ?? {}) };
  const child = (container as Record<string, unknown>)[head];
  const updated = rest.length ? setAt(child ?? (/^\d+$/.test(rest[0]) ? [] : {}), rest.join("."), next) : next;
  if (updated === undefined && !Array.isArray(container)) {
    delete (container as Record<string, unknown>)[head];
  } else {
    (container as Record<string, unknown>)[head] = updated;
  }
  return container as T;
}

export type FieldErrors = Record<string, string>;

const ajv = new Ajv2020({ allErrors: true, strict: false });
addFormats(ajv);

/** Validate with the same JSON Schema the config service uses; key errors by dotted path. */
export function validate(schema: JsonSchema, value: unknown): FieldErrors {
  const check = ajv.compile(schema);
  if (check(value)) return {};
  const errors: FieldErrors = {};
  for (const err of check.errors ?? []) {
    let path = err.instancePath.split("/").filter(Boolean).join(".");
    if (err.keyword === "required" && "missingProperty" in err.params) {
      path = joinPath(path, String(err.params.missingProperty));
    }
    if (err.keyword === "additionalProperties" && "additionalProperty" in err.params) {
      path = joinPath(path, String(err.params.additionalProperty));
    }
    errors[path] ??= err.keyword === "required" ? "required" : (err.message ?? "invalid");
  }
  return errors;
}

/** Map a problem+json "errors" array (config service: {path, message}) to field errors. */
export function problemErrors(errors: { path?: string; message?: string }[] | undefined): FieldErrors {
  const out: FieldErrors = {};
  for (const e of errors ?? []) out[e.path ?? ""] ??= e.message ?? "invalid";
  return out;
}
