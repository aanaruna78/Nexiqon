import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { useState } from "react";

import { SchemaForm } from "@/components/schema-form/schema-form";
import type { JsonSchema } from "@/components/schema-form/schema";
import agentSchema from "../../../../../contracts/schemas/config/agent.schema.json";
import modelSchema from "../../../../../contracts/schemas/config/model_profile.schema.json";

function Demo({ schema, initial = {}, errors }: { schema: JsonSchema; initial?: Record<string, unknown>; errors?: Record<string, string> }) {
  const [value, setValue] = useState(initial);
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
      <SchemaForm schema={schema} value={value} onChange={setValue} errors={errors} />
      <pre className="overflow-auto rounded-lg bg-muted p-3 text-xs" aria-label="Current value">{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}

const meta: Meta<typeof Demo> = { title: "Configuration/SchemaForm", component: Demo };
export default meta;

export const Agent: StoryObj<typeof Demo> = {
  args: { schema: agentSchema as JsonSchema, initial: { display_name: "Acme Help", pack: { name: "saas-knowledge-assistant" } } },
};

export const ModelProfileWithAdvanced: StoryObj<typeof Demo> = {
  args: { schema: modelSchema as JsonSchema },
};

export const WithServerErrors: StoryObj<typeof Demo> = {
  args: {
    schema: agentSchema as JsonSchema,
    initial: { display_name: "x" },
    errors: { display_name: "should NOT have fewer than 2 characters", pack: "required" },
  },
};
