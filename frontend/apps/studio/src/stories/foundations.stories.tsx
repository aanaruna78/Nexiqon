import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { KeyRound, Plus } from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const meta: Meta = { title: "Foundations" };
export default meta;

const SWATCHES = ["primary", "secondary", "accent", "muted", "destructive", "warning-background", "sidebar"];

export const Palette: StoryObj = {
  render: () => (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {SWATCHES.map((name) => (
        <div key={name} className="overflow-hidden rounded-lg border">
          <div className="h-16" style={{ background: `var(--${name})` }} />
          <p className="p-2 font-mono text-xs">--{name}</p>
        </div>
      ))}
    </div>
  ),
};

export const Buttons: StoryObj = {
  render: () => (
    <div className="flex flex-wrap gap-3">
      <Button><Plus aria-hidden="true" />Primary</Button>
      <Button variant="secondary">Secondary</Button>
      <Button variant="outline">Outline</Button>
      <Button variant="ghost">Ghost</Button>
      <Button variant="destructive">Destructive</Button>
      <Button disabled>Disabled</Button>
    </div>
  ),
};

export const StatusBadges: StoryObj = {
  render: () => (
    <div className="flex flex-wrap gap-2">
      <Badge>dev v3</Badge>
      <Badge variant="secondary">Active</Badge>
      <Badge variant="outline">Invited</Badge>
      <Badge variant="destructive">Revoked</Badge>
    </div>
  ),
};

export const Empty: StoryObj = {
  render: () => <EmptyState icon={KeyRound} title="No API keys yet" body="Keys let servers and the chat widget call Nexiqon." action={<Button>Create API key</Button>} />,
};

export const Header: StoryObj = {
  render: () => <PageHeader title="Members & roles" description="Invite people and decide what they can do." actions={<Button>Invite member</Button>} />,
};
