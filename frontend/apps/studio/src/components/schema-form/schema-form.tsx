"use client";

import { ChevronDown, Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState, type KeyboardEvent, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import {
  fieldId,
  fieldKind,
  type FieldErrors,
  getAt,
  isAdvanced,
  joinPath,
  type JsonSchema,
  labelFor,
  setAt,
} from "./schema";

interface Ctx {
  root: unknown;
  set: (path: string, value: unknown) => void;
  errors: FieldErrors;
  prefix: string;
  disabled?: boolean;
}

export interface SchemaFormProps {
  schema: JsonSchema;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  errors?: FieldErrors;
  disabled?: boolean;
}

/** Renders any configuration kind from its JSON Schema with consistent, accessible controls. */
export function SchemaForm({ schema, value, onChange, errors = {}, disabled }: SchemaFormProps) {
  const prefix = useId().replace(/:/g, "");
  const ctx: Ctx = {
    root: value,
    set: (path, next) => onChange(setAt(value, path, next)),
    errors,
    prefix,
    disabled,
  };
  return (
    <div className="space-y-6">
      <ErrorSummary errors={errors} prefix={prefix} />
      <ObjectFields schema={schema} path="" ctx={ctx} />
    </div>
  );
}

function ErrorSummary({ errors, prefix }: { errors: FieldErrors; prefix: string }) {
  const t = useTranslations();
  const entries = Object.entries(errors);
  if (entries.length === 0) return null;
  return (
    <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm">
      <p className="font-medium text-destructive">{t("config.invalid")}</p>
      <ul className="mt-2 list-disc space-y-1 ps-5">
        {entries.map(([path, message]) => (
          <li key={path}>
            <a className="underline underline-offset-2" href={`#${fieldId(prefix, path)}`}>
              {path || "—"}
            </a>
            : {message === "required" ? t("form.required") : message}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ObjectFields({ schema, path, ctx }: { schema: JsonSchema; path: string; ctx: Ctx }) {
  const t = useTranslations("common");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const entries = Object.entries(schema.properties ?? {});
  const basic = entries.filter(([, s]) => !isAdvanced(s));
  const advanced = entries.filter(([, s]) => isAdvanced(s));
  const required = new Set(schema.required ?? []);
  const render = ([key, s]: [string, JsonSchema]) => (
    <Field key={key} name={key} schema={s} path={joinPath(path, key)} required={required.has(key)} ctx={ctx} />
  );
  return (
    <div className="space-y-5">
      {basic.map(render)}
      {advanced.length > 0 ? (
        <Collapsible open={showAdvanced} onOpenChange={setShowAdvanced}>
          <CollapsibleTrigger asChild>
            <Button type="button" variant="ghost" size="sm" className="gap-1 px-0">
              <ChevronDown className={cn("size-4 transition-transform", showAdvanced && "rotate-180")} aria-hidden="true" />
              {showAdvanced ? t("hideAdvanced") : t("showAdvanced")}
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-4 space-y-5 border-s-2 ps-4">{advanced.map(render)}</CollapsibleContent>
        </Collapsible>
      ) : null}
    </div>
  );
}

function Shell({
  id,
  label,
  required,
  description,
  error,
  children,
  inline,
}: {
  id: string;
  label: string;
  required?: boolean;
  description?: string;
  error?: string;
  children: ReactNode;
  inline?: boolean;
}) {
  const t = useTranslations();
  return (
    <div className={cn("space-y-2", inline && "flex items-start justify-between gap-4 space-y-0")}>
      <div className="space-y-1">
        <Label htmlFor={id}>
          {label}
          {required ? <span className="text-destructive" aria-hidden="true"> *</span> : null}
        </Label>
        {description ? (
          <p id={`${id}-help`} className="text-sm text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
      {children}
      {error ? (
        <p id={`${id}-error`} className="text-sm font-medium text-destructive">
          {error === "required" ? t("form.required") : error}
        </p>
      ) : null}
    </div>
  );
}

function describedBy(id: string, schema: JsonSchema, error?: string): string | undefined {
  const ids = [schema.description ? `${id}-help` : null, error ? `${id}-error` : null].filter(Boolean);
  return ids.length ? ids.join(" ") : undefined;
}

function Field({ name, schema, path, required, ctx }: { name: string; schema: JsonSchema; path: string; required: boolean; ctx: Ctx }) {
  const t = useTranslations();
  const id = fieldId(ctx.prefix, path);
  const label = labelFor(name, schema);
  const value = getAt(ctx.root, path);
  const error = ctx.errors[path];
  const aria = { "aria-describedby": describedBy(id, schema, error), "aria-invalid": error ? true : undefined, "aria-required": required || undefined };
  const kind = fieldKind(schema);

  switch (kind) {
    case "object":
      return (
        <fieldset id={id} className="space-y-4 rounded-lg border p-4">
          <legend className="px-1 text-sm font-semibold">{label}</legend>
          {schema.description ? <p className="text-sm text-muted-foreground">{schema.description}</p> : null}
          <ObjectFields schema={schema} path={path} ctx={ctx} />
        </fieldset>
      );
    case "const":
      return (
        <Shell id={id} label={label} description={schema.description}>
          <Input id={id} value={String(schema.const)} readOnly disabled {...aria} />
        </Shell>
      );
    case "boolean":
      return (
        <Shell id={id} label={label} description={schema.description} error={error} inline>
          <Switch id={id} checked={value === true} disabled={ctx.disabled} onCheckedChange={(v) => ctx.set(path, v)} {...aria} />
        </Shell>
      );
    case "enum":
      return (
        <Shell id={id} label={label} required={required} description={schema.description} error={error}>
          <Select value={value === undefined ? "" : String(value)} disabled={ctx.disabled} onValueChange={(v) => ctx.set(path, schema.enum?.find((o) => String(o) === v))}>
            <SelectTrigger id={id} className="w-full sm:w-80" {...aria}>
              <SelectValue placeholder="—" />
            </SelectTrigger>
            <SelectContent>
              {schema.enum?.map((option) => (
                <SelectItem key={String(option)} value={String(option)}>
                  {String(option)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Shell>
      );
    case "number":
      return (
        <Shell id={id} label={label} required={required} description={schema.description} error={error}>
          <Input
            id={id}
            type="number"
            inputMode="decimal"
            className="w-full sm:w-48"
            min={schema.minimum}
            max={schema.maximum}
            step={schema.type === "integer" ? 1 : "any"}
            value={typeof value === "number" ? value : ""}
            disabled={ctx.disabled}
            onChange={(e) => ctx.set(path, e.target.value === "" ? undefined : Number(e.target.value))}
            {...aria}
          />
        </Shell>
      );
    case "color":
      return (
        <Shell id={id} label={label} required={required} description={schema.description} error={error}>
          <div className="flex items-center gap-2">
            <input
              type="color"
              aria-label={label}
              className="size-9 cursor-pointer rounded border"
              value={typeof value === "string" ? value : "#0e8a7e"}
              disabled={ctx.disabled}
              onChange={(e) => ctx.set(path, e.target.value)}
            />
            <Input id={id} className="w-32 font-mono" value={typeof value === "string" ? value : ""} disabled={ctx.disabled} onChange={(e) => ctx.set(path, e.target.value || undefined)} {...aria} />
          </div>
        </Shell>
      );
    case "textarea":
      return (
        <Shell id={id} label={label} required={required} description={schema.description} error={error}>
          <Textarea id={id} rows={4} value={typeof value === "string" ? value : ""} disabled={ctx.disabled} onChange={(e) => ctx.set(path, e.target.value || undefined)} {...aria} />
        </Shell>
      );
    case "text":
      return (
        <Shell id={id} label={label} required={required} description={schema.description} error={error}>
          <Input
            id={id}
            value={typeof value === "string" ? value : ""}
            type={schema.format === "uri" ? "url" : "text"}
            maxLength={schema.maxLength}
            disabled={ctx.disabled}
            onChange={(e) => ctx.set(path, e.target.value || undefined)}
            {...aria}
          />
        </Shell>
      );
    case "string-list":
      return (
        <Shell id={id} label={label} required={required} description={schema.description} error={error}>
          <TagInput id={id} values={Array.isArray(value) ? (value as string[]) : []} disabled={ctx.disabled} onChange={(v) => ctx.set(path, v.length ? v : undefined)} aria={aria} />
        </Shell>
      );
    case "string-map":
      return (
        <Shell id={id} label={label} required={required} description={schema.description} error={error}>
          <StringMap id={id} value={(value as Record<string, string>) ?? {}} disabled={ctx.disabled} onChange={(v) => ctx.set(path, Object.keys(v).length ? v : undefined)} />
        </Shell>
      );
    case "object-list": {
      const items = Array.isArray(value) ? (value as unknown[]) : [];
      const itemSchema = schema.items ?? {};
      return (
        <fieldset id={id} className="space-y-3 rounded-lg border p-4">
          <legend className="px-1 text-sm font-semibold">{label}</legend>
          {schema.description ? <p className="text-sm text-muted-foreground">{schema.description}</p> : null}
          {items.map((_, index) => (
            <div key={index} className="space-y-4 rounded-md bg-muted/50 p-4">
              <div className="flex items-center justify-between">
                <Badge variant="secondary">#{index + 1}</Badge>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={ctx.disabled}
                  aria-label={t("form.removeItem", { item: `${label} #${index + 1}` })}
                  onClick={() => ctx.set(path, items.filter((__, i) => i !== index))}
                >
                  <X className="size-4" aria-hidden="true" />
                </Button>
              </div>
              <ObjectFields schema={itemSchema} path={joinPath(path, index)} ctx={ctx} />
            </div>
          ))}
          <Button type="button" variant="outline" size="sm" disabled={ctx.disabled} onClick={() => ctx.set(path, [...items, {}])}>
            <Plus className="size-4" aria-hidden="true" />
            {t("form.add")}
          </Button>
          {error ? <p className="text-sm font-medium text-destructive">{error}</p> : null}
        </fieldset>
      );
    }
    default:
      return (
        <Shell id={id} label={label} required={required} description={schema.description} error={error}>
          <JsonEditor id={id} value={value} disabled={ctx.disabled} onChange={(v) => ctx.set(path, v)} aria={aria} />
        </Shell>
      );
  }
}

type Aria = Record<string, string | boolean | undefined>;

function TagInput({ id, values, onChange, disabled, aria }: { id: string; values: string[]; onChange: (v: string[]) => void; disabled?: boolean; aria: Aria }) {
  const t = useTranslations("form");
  const [draft, setDraft] = useState("");
  const add = () => {
    const v = draft.trim();
    if (v && !values.includes(v)) onChange([...values, v]);
    setDraft("");
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add();
    } else if (e.key === "Backspace" && !draft && values.length) {
      onChange(values.slice(0, -1));
    }
  };
  return (
    <div className="space-y-2">
      {values.length ? (
        <ul className="flex flex-wrap gap-2" aria-label="values">
          {values.map((v) => (
            <li key={v}>
              <Badge variant="secondary" className="gap-1 ps-2.5">
                {v}
                <button type="button" className="rounded-full p-0.5 hover:bg-background/60" disabled={disabled} aria-label={t("removeItem", { item: v })} onClick={() => onChange(values.filter((x) => x !== v))}>
                  <X className="size-3" aria-hidden="true" />
                </button>
              </Badge>
            </li>
          ))}
        </ul>
      ) : null}
      <Input id={id} value={draft} placeholder={t("itemPlaceholder")} disabled={disabled} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} onBlur={add} {...aria} />
    </div>
  );
}

function StringMap({ id, value, onChange, disabled }: { id: string; value: Record<string, string>; onChange: (v: Record<string, string>) => void; disabled?: boolean }) {
  const t = useTranslations();
  const rows = Object.entries(value);
  const [newKey, setNewKey] = useState("");
  return (
    <div id={id} className="space-y-2">
      {rows.map(([k, v]) => (
        <div key={k} className="flex items-center gap-2">
          <Badge variant="outline" className="min-w-12 justify-center font-mono">{k}</Badge>
          <Input aria-label={k} value={v} disabled={disabled} onChange={(e) => onChange({ ...value, [k]: e.target.value })} />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={disabled}
            aria-label={t("form.removeItem", { item: k })}
            onClick={() => {
              const next = { ...value };
              delete next[k];
              onChange(next);
            }}
          >
            <X className="size-4" aria-hidden="true" />
          </Button>
        </div>
      ))}
      <div className="flex items-center gap-2">
        <Input className="w-28 font-mono" aria-label={t("form.itemPlaceholder")} placeholder="en" value={newKey} disabled={disabled} onChange={(e) => setNewKey(e.target.value.trim())} />
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled || !newKey || newKey in value}
          onClick={() => {
            onChange({ ...value, [newKey]: "" });
            setNewKey("");
          }}
        >
          <Plus className="size-4" aria-hidden="true" />
          {t("form.add")}
        </Button>
      </div>
    </div>
  );
}

function JsonEditor({ id, value, onChange, disabled, aria }: { id: string; value: unknown; onChange: (v: unknown) => void; disabled?: boolean; aria: Aria }) {
  const t = useTranslations("form");
  const [text, setText] = useState(() => (value === undefined ? "" : JSON.stringify(value, null, 2)));
  const [invalid, setInvalid] = useState(false);
  return (
    <div className="space-y-1">
      <Textarea
        id={id}
        rows={6}
        className="font-mono text-xs"
        value={text}
        disabled={disabled}
        spellCheck={false}
        onChange={(e) => {
          setText(e.target.value);
          if (!e.target.value.trim()) {
            setInvalid(false);
            onChange(undefined);
            return;
          }
          try {
            onChange(JSON.parse(e.target.value));
            setInvalid(false);
          } catch {
            setInvalid(true);
          }
        }}
        {...aria}
      />
      {invalid ? <p className="text-sm text-destructive">{t("invalid")} (JSON)</p> : null}
    </div>
  );
}
