import { describe, expect, it } from "vitest";

import { slugify } from "@/components/knowledge/collections";
import {
  answerParts,
  checkFile,
  documentLabel,
  errorHintKey,
  formatBytes,
  highlight,
  type PluginManifest,
  type Run,
  runProgress,
  uploadRules,
} from "@/lib/knowledge";

const parser = (extensions: string[], media: string[]): PluginManifest => ({
  name: "p",
  kind: "parser",
  title: "P",
  description: "",
  config_schema: {},
  capabilities: [],
  media_types: media,
  extensions,
  icon: null,
});

const run = (over: Partial<Run>): Run => ({
  id: "r",
  collection_id: "c",
  source_id: null,
  kind: "sync",
  status: "running",
  workflow_id: null,
  discovered: 0,
  processed: 0,
  unchanged: 0,
  failed: 0,
  quarantined: 0,
  deleted: 0,
  truncated: false,
  incomplete: false,
  warnings: [],
  error: null,
  created_at: "",
  started_at: null,
  finished_at: null,
  ...over,
});

describe("knowledge helpers", () => {
  it("builds upload rules from parser manifests and checks files", () => {
    const rules = uploadRules([parser([".md", ".PDF"], ["text/markdown"]), parser([".pdf"], ["application/pdf"])], 1000);
    expect(rules.extensions).toEqual([".md", ".pdf"]);
    expect(rules.accept).toBe(".md,.pdf,application/pdf,text/markdown");
    expect(checkFile({ name: "Guide.PDF", size: 10 }, rules)).toBeNull();
    expect(checkFile({ name: "a.zip", size: 10 }, rules)).toBe("unsupported_type");
    expect(checkFile({ name: "a.md", size: 2000 }, rules)).toBe("too_large");
    expect(checkFile({ name: "a.md", size: 0 }, rules)).toBe("empty");
  });

  it("computes run progress from counters", () => {
    expect(runProgress(run({ discovered: 10, processed: 3, unchanged: 2, failed: 1 }))).toEqual({ done: 6, total: 10, ratio: 0.6 });
    expect(runProgress(run({ discovered: 0 })).ratio).toBe(0);
    expect(runProgress(run({ status: "completed" })).ratio).toBe(1);
  });

  it("maps error codes to hint keys", () => {
    expect(errorHintKey("malware_detected")).toBe("malware_detected");
    expect(errorHintKey("something_new")).toBe("unknown");
    expect(errorHintKey(null)).toBe("unknown");
  });

  it("highlights query words, case-insensitively and in any script", () => {
    expect(highlight("Backups run nightly", "when do BACKUPS run")).toEqual([
      { text: "Backups", match: true },
      { text: " ", match: false },
      { text: "run", match: true },
      { text: " nightly", match: false },
    ]);
    expect(highlight("تنتهي صلاحية الدعوات", "صلاحية").filter((s) => s.match).map((s) => s.text)).toEqual(["صلاحية"]);
    expect(highlight("a (b) c", "(b)")).toEqual([{ text: "a (b) c", match: false }]);
  });

  it("splits answers into text and citation markers", () => {
    expect(answerParts("Kept 35 days [1][2].")).toEqual([{ text: "Kept 35 days " }, { marker: "1" }, { marker: "2" }, { text: "." }]);
  });

  it("labels documents and formats sizes", () => {
    expect(documentLabel({ title: null, uri: "upload://guide.md" })).toBe("guide.md");
    expect(documentLabel({ title: null, uri: "https://docs.example.com/a/b?x=1" })).toBe("b");
    expect(documentLabel({ title: "Guide", uri: "x" })).toBe("Guide");
    expect(formatBytes(50 * 1024 * 1024)).toBe("50 MB");
    expect(formatBytes(512)).toBe("512 byte");
  });

  it("slugifies collection names", () => {
    expect(slugify("Product Docs (EU)")).toBe("product-docs-eu");
    expect(slugify("--Ünïcode--")).toBe("unicode");
  });
});
