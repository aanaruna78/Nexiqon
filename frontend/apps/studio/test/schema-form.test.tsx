import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { NextIntlClientProvider } from "next-intl";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { SchemaForm } from "@/components/schema-form/schema-form";
import type { FieldErrors, JsonSchema } from "@/components/schema-form/schema";
import messages from "../messages/en.json";

const schema: JsonSchema = {
  type: "object",
  required: ["display_name"],
  properties: {
    display_name: { type: "string", title: "Display name", description: "Shown to end users" },
    cite_sources: { type: "boolean", title: "Cite sources" },
    tools: { type: "array", items: { type: "string" }, title: "Tools" },
    min_evidence_score: { type: "number", minimum: 0, maximum: 1, "x-ui": { advanced: true } },
  },
};

function Harness({ errors, onValue }: { errors?: FieldErrors; onValue?: (v: Record<string, unknown>) => void }) {
  const [value, setValue] = useState<Record<string, unknown>>({});
  return (
    <NextIntlClientProvider locale="en" messages={messages}>
      <SchemaForm
        schema={schema}
        value={value}
        errors={errors}
        onChange={(v) => {
          setValue(v);
          onValue?.(v);
        }}
      />
    </NextIntlClientProvider>
  );
}

describe("SchemaForm", () => {
  it("renders labelled, described controls and updates the value", async () => {
    let latest: Record<string, unknown> = {};
    render(<Harness onValue={(v) => (latest = v)} />);
    const name = screen.getByLabelText(/Display name/);
    expect(name).toHaveAccessibleDescription("Shown to end users");
    expect(name).toHaveAttribute("aria-required", "true");
    await userEvent.type(name, "Help");
    await userEvent.click(screen.getByRole("switch", { name: "Cite sources" }));
    const tools = screen.getByLabelText("Tools");
    await userEvent.type(tools, "account-lookup{Enter}");
    expect(latest).toEqual({ display_name: "Help", cite_sources: true, tools: ["account-lookup"] });
    await userEvent.click(screen.getByRole("button", { name: "Remove account-lookup" }));
    expect(latest.tools).toBeUndefined();
  });

  it("hides advanced settings behind a disclosure", async () => {
    render(<Harness />);
    expect(screen.queryByLabelText("Min evidence score")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show advanced settings" }));
    expect(screen.getByLabelText("Min evidence score")).toBeInTheDocument();
  });

  it("shows an error summary linked to fields", () => {
    render(<Harness errors={{ display_name: "required" }} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Some settings need attention");
    const link = screen.getByRole("link", { name: "display_name" });
    const field = screen.getByLabelText(/Display name/);
    expect(link.getAttribute("href")).toBe(`#${field.id}`);
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAccessibleDescription(/This field is required/);
  });

  it("has no axe violations", async () => {
    const { container } = render(<Harness errors={{ display_name: "required" }} />);
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});
